"""Reader for HDF5 files and the netCDF-4 files stored in them.

A netCDF-4 file is an HDF5 file that follows conventions: a dimension is a
dataset marked as a *dimension scale*, a variable refers to its dimensions
through the attribute `DIMENSION_LIST`, and a handful of attributes carry
bookkeeping of the netCDF library. This reader applies the conventions where it
finds them and otherwise presents the file as it is, so that one reader serves
the netCDF-4 files of Calliope and PyPSA and the plain HDF5 files of
AdOpT-NET0.

Two properties of HDF5 need care. Links can form cycles, which would make a
walk endless; a group that has been visited is not entered again. And a link
can point into another file; such external links are reported but not followed,
because a file must not be able to make the reader open a path of its choosing.
"""

from __future__ import annotations

import functools
import posixpath
from pathlib import Path
from typing import Any, Final

import h5py
import numpy as np

from coati.errors import SourceError
from coati.masked import all_missing
from coati.model import Dataset, Dimension, Group, Variable

__all__ = ["open_hdf5"]

# Attributes of the netCDF library and of the HDF5 dimension scales: bookkeeping, not content.
_BOOKKEEPING: Final = frozenset(
    {
        "DIMENSION_LIST",
        "REFERENCE_LIST",
        "_NCProperties",
        "_Netcdf4Coordinates",
        "_Netcdf4Dimid",
        "_nc3_strict",
    }
)

_SCALE_ATTRIBUTES: Final = frozenset({"CLASS", "NAME"})

# The name the netCDF library gives the scale of a dimension that has no variable.
_DIMENSION_ONLY: Final = "This is a netCDF dimension but not a netCDF variable."

# The prefix the netCDF library puts before a variable that shares the name of a
# dimension without being its coordinate variable.
_NOT_A_COORDINATE: Final = "_nc4_non_coord_"

_READ_ERRORS: Final = (KeyError, OSError, RuntimeError, TypeError, ValueError)


def open_hdf5(path: Path) -> Dataset:
    """Open the HDF5 or netCDF-4 file `path` and read its structure.

    Raises:
        SourceError: The file cannot be opened or is not an HDF5 file.
    """
    try:
        file = h5py.File(path, "r", locking=False)
    except OSError as error:
        raise SourceError(f"{path}: cannot be opened as HDF5: {_reason(error)}") from error
    try:
        return _Builder(file, path).build()
    except BaseException:
        file.close()
        raise


def _members(group: h5py.Group) -> list[str]:
    """Return the names of the members of a group.

    They are in the order of their creation if the file records it, as every
    netCDF-4 file does, and in the order of their names otherwise. Newer
    versions of h5py iterate in this order, older ones always by name; what
    is read must not depend on the version.
    """
    names: list[bytes] = []
    group.id.links.iterate(names.append, idx_type=_index(group, links=True))
    return [name.decode("utf-8", "surrogateescape") for name in names]


def _attribute_names(source: Any) -> list[str]:
    """Return the names of the attributes of an object, ordered like the members of a group."""
    names: list[Any] = []

    def note(name: Any, *_: Any) -> None:
        names.append(name)

    h5py.h5a.iterate(source.id, note, index_type=_index(source, links=False))
    return [
        name.decode("utf-8", "surrogateescape") if isinstance(name, bytes) else str(name)
        for name in names
    ]


def _index(source: Any, *, links: bool) -> int:
    """Return the index to iterate by: that of creation if the file keeps one, else of names."""
    try:
        # A file is asked as its root group: what a file says about itself is another matter.
        owner = source["/"] if isinstance(source, h5py.File) else source
        created = owner.id.get_create_plist()
        order = created.get_link_creation_order() if links else created.get_attr_creation_order()
    except (AttributeError, *_READ_ERRORS):
        return int(h5py.h5.INDEX_NAME)
    tracked = order & h5py.h5p.CRT_ORDER_TRACKED
    return int(h5py.h5.INDEX_CRT_ORDER if tracked else h5py.h5.INDEX_NAME)


class _Builder:
    """Builds the description of one open file."""

    def __init__(self, file: h5py.File, path: Path) -> None:
        self._file = file
        self._path = path
        self._warnings: list[str] = []
        self._visited: dict[Any, str] = {}
        self._netcdf = False

    def build(self) -> Dataset:
        dataset = Dataset(name="", path="/", source=self._path, _closer=self._file.close)
        properties = self._text_attribute(self._file, "_NCProperties")
        if properties is not None:
            dataset.properties["_NCProperties"] = properties
            self._netcdf = True
        self._visited[self._file.id] = "/"
        self._fill(dataset, self._file)
        _grow_unlimited(dataset)
        dataset.format = "netcdf4" if self._netcdf else "hdf5"
        dataset.warnings = self._warnings
        return dataset

    # -- groups -----------------------------------------------------------------------------

    def _fill(self, group: Group, source: h5py.Group) -> None:
        group.attributes = self._attributes(source, group.path)
        for name in _members(source):
            path = posixpath.join(group.path, name)
            member = self._member(source, name, path)
            if isinstance(member, h5py.Dataset):
                self._add_dataset(group, name, path, member)
            elif isinstance(member, h5py.Group):
                self._add_group(group, name, path, member)

    def _member(self, source: h5py.Group, name: str, path: str) -> Any:
        """Return the object the link `name` leads to, or `None` if it is not followed."""
        try:
            link = source.get(name, getlink=True)
            if isinstance(link, h5py.ExternalLink):
                self._warn(f"{path} is a link into the file {link.filename!r}; it is not followed")
                return None
            return source[name]
        except _READ_ERRORS as error:
            self._warn(f"{path} cannot be opened: {_reason(error)}")
            return None

    def _add_group(self, parent: Group, name: str, path: str, source: h5py.Group) -> None:
        seen = self._visited.get(source.id)
        if seen is not None:
            self._warn(f"{path} is the group {seen}, which is already listed; it is not repeated")
            return
        self._visited[source.id] = path
        child = Group(name=name, path=path, parent=parent)
        parent.groups[name] = child
        self._fill(child, source)

    def _add_dataset(self, group: Group, name: str, path: str, source: h5py.Dataset) -> None:
        scale = _is_scale(source)
        if scale:
            self._netcdf = self._netcdf or "_Netcdf4Dimid" in source.attrs
            if source.shape:
                unlimited = source.maxshape[0] is None
                group.dimensions[name] = Dimension(name, int(source.shape[0]), unlimited)
            if self._text_attribute(source, "NAME", "").startswith(_DIMENSION_ONLY):
                return
        if name.startswith(_NOT_A_COORDINATE):
            name = name[len(_NOT_A_COORDINATE) :]
            path = posixpath.join(group.path, name)
        group.variables[name] = self._variable(name, path, source, scale)

    # -- variables --------------------------------------------------------------------------

    def _variable(self, name: str, path: str, source: h5py.Dataset, scale: bool) -> Variable:
        shape = tuple(int(size) for size in source.shape) if source.shape is not None else ()
        dimensions = self._dimensions(name, source, scale)
        named = bool(dimensions) and None not in dimensions
        kind, type_name, enumeration = _describe(source.dtype, named=named)
        if source.shape is None:
            kind = "empty"
        return Variable(
            name=name,
            path=path,
            dtype=np.dtype(object) if kind in ("text", "bytes") else source.dtype,
            shape=shape,
            dimensions=dimensions,
            attributes=self._attributes(source, path, scale=scale),
            type_name=type_name,
            enumeration=enumeration,
            reader=functools.partial(_read, source, kind, path),
        )

    def _dimensions(self, name: str, source: h5py.Dataset, scale: bool) -> tuple[str | None, ...]:
        if source.shape is None or not source.shape:
            return ()
        if scale and len(source.shape) == 1:
            return (name,)
        names: list[str | None] = []
        for axis in range(len(source.shape)):
            try:
                scales = source.dims[axis]
                attached = scales[0].name if len(scales) else None
            except _READ_ERRORS:
                attached = None
            names.append(posixpath.basename(attached) if attached else None)
        return tuple(names)

    # -- attributes -------------------------------------------------------------------------

    def _attributes(self, source: Any, path: str, *, scale: bool = False) -> dict[str, Any]:
        attributes: dict[str, Any] = {}
        for name in _attribute_names(source):
            if name in _BOOKKEEPING or (scale and name in _SCALE_ATTRIBUTES):
                continue
            try:
                attributes[name] = self._attribute(source.attrs[name])
            except _READ_ERRORS as error:
                self._warn(f"the attribute {name!r} of {path} cannot be read: {_reason(error)}")
        return attributes

    def _attribute(self, value: Any) -> Any:
        if isinstance(value, h5py.Empty):
            return None
        if isinstance(value, (bytes, np.bytes_)):
            return bytes(value).decode("utf-8", "replace")
        if isinstance(value, str):
            return str(value)
        if isinstance(value, (h5py.Reference, h5py.RegionReference)):
            return _target(self._file, value)
        if isinstance(value, np.ndarray):
            return self._attribute_array(value)
        if isinstance(value, np.generic) and not isinstance(value, np.void):
            return value.item()
        return value

    def _attribute_array(self, value: np.ndarray[Any, Any]) -> Any:
        if h5py.check_ref_dtype(value.dtype) is not None:
            targets = [_target(self._file, item) for item in value.ravel()]
            return targets[0] if value.ndim == 0 else targets
        if value.dtype.kind in "SU" or _holds_text(value):
            texts = [_as_text(item) for item in value.ravel()]
            return texts[0] if value.ndim == 0 else texts
        if value.dtype.kind in "biufc" and value.shape in ((), (1,)):
            return value.reshape(()).item()
        return value

    def _text_attribute(self, source: Any, name: str, default: str | None = None) -> Any:
        try:
            value = source.attrs.get(name)
        except _READ_ERRORS:
            return default
        if isinstance(value, (bytes, np.bytes_)):
            return bytes(value).decode("utf-8", "replace")
        return str(value) if isinstance(value, str) else default

    def _warn(self, message: str) -> None:
        self._warnings.append(message)


def _grow_unlimited(dataset: Dataset) -> None:
    """Give every unlimited dimension the length of the longest variable along it.

    The netCDF library does not record the length of an unlimited dimension
    that has no coordinate variable; the length is that of the variables.
    """
    for group in dataset.walk():
        for variable in group.variables.values():
            for name, length in zip(variable.dimensions, variable.shape, strict=True):
                owner = _owner(group, name)
                if owner is None or name is None:
                    continue
                known = owner.dimensions[name]
                if known.unlimited and length > known.size:
                    owner.dimensions[name] = Dimension(name, length, unlimited=True)


def _owner(group: Group, name: str | None) -> Group | None:
    """Return the group that defines the dimension `name` visible in `group`."""
    node: Group | None = group
    while node is not None and name is not None:
        if name in node.dimensions:
            return node
        node = node.parent
    return None


def _is_scale(source: h5py.Dataset) -> bool:
    try:
        marker = source.attrs.get("CLASS")
    except _READ_ERRORS:
        return False
    return isinstance(marker, (bytes, np.bytes_, str)) and _as_text(marker) == "DIMENSION_SCALE"


def _describe(dtype: np.dtype[Any], *, named: bool) -> tuple[str, str, dict[str, int] | None]:
    """Return how to read values of `dtype`, the name of the type and its enumeration.

    Args:
        dtype: The type of a dataset.
        named: Whether the axes of the dataset have dimensions, which makes a
            dataset of single characters a netCDF character array.
    """
    text = h5py.check_string_dtype(dtype)
    if text is not None:
        if text.length == 1 and named:
            return "numbers", "char", None
        return ("text" if text.length is None else "bytes"), "string", None
    enumeration = h5py.check_enum_dtype(dtype)
    if enumeration is not None:
        return "numbers", dtype.name, {name: int(value) for name, value in enumeration.items()}
    if h5py.check_ref_dtype(dtype) is not None:
        return "references", "reference", None
    element = h5py.check_vlen_dtype(dtype)
    if element is not None:
        return "numbers", f"vlen<{np.dtype(element).name}>", None
    if dtype.names:
        return "numbers", "compound", None
    if dtype.kind == "V":
        return "numbers", "opaque", None
    return "numbers", dtype.name, None


def _read(source: h5py.Dataset, kind: str, path: str) -> np.ndarray[Any, Any]:
    """Read the values of a dataset; see `coati.model.Variable.read`."""
    try:
        if kind == "empty":
            return all_missing((), np.float64)
        if kind == "text":
            return np.asarray(source.asstr(encoding="utf-8", errors="replace")[()], dtype=object)
        values = np.asarray(source[()])
    except _READ_ERRORS as error:
        raise SourceError(f"{path} cannot be read: {_reason(error)}") from error
    if kind == "bytes":
        return np.asarray(np.char.decode(values, "utf-8", "replace")).astype(object)
    if kind == "references":
        targets = [_target(source.file, item) for item in values.ravel()]
        result = np.empty(values.shape, dtype=object)
        result.ravel()[:] = targets
        return result
    return values


def _target(file: h5py.File, reference: Any) -> str | None:
    """Return the path of the object `reference` points to, or `None`."""
    if not reference:
        return None
    try:
        name = file[reference].name
    except _READ_ERRORS:
        return None
    return str(name) if name else None


def _holds_text(value: np.ndarray[Any, Any]) -> bool:
    if value.dtype.kind != "O" or value.size == 0:
        return False
    return all(isinstance(item, (str, bytes, np.bytes_)) for item in value.ravel())


def _as_text(value: Any) -> str:
    if isinstance(value, (bytes, np.bytes_)):
        return bytes(value).decode("utf-8", "replace")
    return str(value)


def _reason(error: BaseException) -> str:
    """Return the message of `error` without the repetition HDF5 adds to it."""
    text = str(error).strip() or type(error).__name__
    return text.splitlines()[0]
