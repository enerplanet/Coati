"""Reader for the classic netCDF formats: CDF-1, CDF-2 and CDF-5.

The classic formats predate netCDF-4 and do not use HDF5. A file is a header
followed by the values, all in big-endian byte order:

* **CDF-1**, the original format, with 32-bit offsets and sizes;
* **CDF-2**, the *64-bit offset* format, which lifts the limit on the file size;
* **CDF-5**, the *64-bit data* format, which also lifts the limit on the size of
  a variable and adds unsigned and 64-bit integers.

The reader follows the [format specification][netcdf-formats] of the netCDF
library. It needs nothing but NumPy. A classic file has one group, no user-defined types and at
most one unlimited dimension, whose variables are stored record by record
after all others.

Every length and offset of the header is checked against the size of the file
before it is used, so a damaged or hostile file is refused instead of causing a
large allocation or a read outside the file.

[netcdf-formats]: https://docs.unidata.ucar.edu/netcdf-c/current/file_format_specifications.html
"""

from __future__ import annotations

import functools
import mmap
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np

from coati.errors import SourceError
from coati.model import Dataset, Dimension, Variable

__all__ = ["open_classic"]

_FORMATS: Final = {
    1: "netcdf3-classic",
    2: "netcdf3-64bit-offset",
    5: "netcdf3-64bit-data",
}

_DIMENSION: Final = 0x0A
_VARIABLE: Final = 0x0B
_ATTRIBUTE: Final = 0x0C

_CHAR: Final = 2

# nc_type -> (type in the file, name of the type)
_TYPES: Final[dict[int, tuple[str, str]]] = {
    1: (">i1", "int8"),
    _CHAR: ("S1", "char"),
    3: (">i2", "int16"),
    4: (">i4", "int32"),
    5: (">f4", "float32"),
    6: (">f8", "float64"),
    7: (">u1", "uint8"),
    8: (">u2", "uint16"),
    9: (">u4", "uint32"),
    10: (">i8", "int64"),
    11: (">u8", "uint64"),
}

# Types that only CDF-5 defines.
_CDF5_ONLY: Final = frozenset({7, 8, 9, 10, 11})


@dataclass(frozen=True)
class _Layout:
    """Where the values of a variable are and how they are arranged."""

    dtype: np.dtype[Any]
    shape: tuple[int, ...]
    begin: int
    record: bool


class _Cursor:
    """Reads the header of a file, never beyond its end."""

    def __init__(self, buffer: mmap.mmap, path: Path, version: int) -> None:
        self._buffer = buffer
        self._path = path
        self._wide = version == 5
        self._wide_offsets = version in (2, 5)
        self.position = 4

    def fail(self, message: str) -> SourceError:
        return SourceError(f"{self._path}: damaged netCDF file: {message}")

    def _unpack(self, code: str, size: int) -> int:
        if self.position + size > len(self._buffer):
            raise self.fail("the header ends unexpectedly")
        (value,) = struct.unpack_from(code, self._buffer, self.position)
        self.position += size
        return int(value)

    def int32(self) -> int:
        return self._unpack(">i", 4)

    def count(self) -> int:
        """Read a number of elements, which must not be negative."""
        value = self._unpack(">q", 8) if self._wide else self._unpack(">i", 4)
        if value < 0:
            raise self.fail(f"a negative count ({value})")
        return value

    def record_count(self) -> int | None:
        """Read the number of records; `None` if the file does not state it."""
        if self._wide:
            value = self._unpack(">Q", 8)
            return None if value == 0xFFFF_FFFF_FFFF_FFFF else value
        value = self._unpack(">I", 4)
        return None if value == 0xFFFF_FFFF else value

    def offset(self) -> int:
        value = self._unpack(">q", 8) if self._wide_offsets else self._unpack(">i", 4)
        if value < 0:
            raise self.fail(f"a negative offset ({value})")
        return value

    def take(self, size: int) -> bytes:
        """Read `size` bytes and the padding that aligns the next item."""
        padded = size + (-size % 4)
        if size < 0 or self.position + padded > len(self._buffer):
            raise self.fail("the header ends unexpectedly")
        value = bytes(self._buffer[self.position : self.position + size])
        self.position += padded
        return value

    def name(self) -> str:
        return self.take(self.count()).decode("utf-8", "replace")

    def list_header(self, tag: int, what: str) -> int:
        """Read the tag and the length of a list; an absent list has length zero."""
        found = self.int32()
        length = self.count()
        if found == 0 and length == 0:
            return 0
        if found != tag:
            raise self.fail(f"the list of {what} starts with the tag {found:#x}")
        return length


def open_classic(path: Path) -> Dataset:
    """Open the file `path` in a classic netCDF format and read its structure.

    Raises:
        SourceError: The file cannot be opened or is not a valid classic file.
    """
    try:
        with path.open("rb") as stream:
            buffer = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
    except (OSError, ValueError) as error:
        raise SourceError(f"{path}: cannot be read: {error}") from error
    try:
        return _build(buffer, path)
    except BaseException:
        buffer.close()
        raise


def _build(buffer: mmap.mmap, path: Path) -> Dataset:
    version = buffer[3] if len(buffer) >= 4 and buffer[:3] == b"CDF" else 0
    if version not in _FORMATS:
        raise SourceError(f"{path}: not a classic netCDF file")
    cursor = _Cursor(buffer, path, version)
    records = cursor.record_count()
    dimensions = _read_dimensions(cursor)
    dataset = Dataset(
        name="",
        path="/",
        source=path,
        format=_FORMATS[version],
        _closer=buffer.close,
    )
    dataset.attributes = _read_attributes(cursor, version)
    headers = _read_variables(cursor, version, dimensions)
    records = _record_count(records, headers, len(buffer))
    record_size = _record_size(headers)
    for name, size in dimensions:
        unlimited = size is None
        dataset.dimensions[name] = Dimension(name, records if size is None else size, unlimited)
    for header in headers:
        variable = _variable(header, records, record_size, buffer, path)
        dataset.variables[variable.name] = variable
    return dataset


def _read_dimensions(cursor: _Cursor) -> list[tuple[str, int | None]]:
    """Read the dimensions; the size of the unlimited one is `None`."""
    dimensions: list[tuple[str, int | None]] = []
    for _ in range(cursor.list_header(_DIMENSION, "dimensions")):
        name = cursor.name()
        size = cursor.count()
        dimensions.append((name, size or None))
    if sum(size is None for _, size in dimensions) > 1:
        raise cursor.fail("more than one unlimited dimension")
    return dimensions


def _read_attributes(cursor: _Cursor, version: int) -> dict[str, Any]:
    attributes: dict[str, Any] = {}
    for _ in range(cursor.list_header(_ATTRIBUTE, "attributes")):
        name = cursor.name()
        dtype, _ = _type(cursor, version)
        length = cursor.count()
        raw = cursor.take(length * dtype.itemsize)
        attributes[name] = _attribute(raw, dtype, length)
    return attributes


def _attribute(raw: bytes, dtype: np.dtype[Any], length: int) -> Any:
    if dtype.kind == "S":
        return raw.rstrip(b"\x00").decode("utf-8", "replace")
    values = np.frombuffer(raw, dtype=dtype, count=length).astype(dtype.newbyteorder("="))
    return values[0].item() if length == 1 else values


def _type(cursor: _Cursor, version: int) -> tuple[np.dtype[Any], str]:
    code = cursor.int32()
    if code not in _TYPES or (code in _CDF5_ONLY and version != 5):
        raise cursor.fail(f"the unknown type {code}")
    dtype, name = _TYPES[code]
    return np.dtype(dtype), name


@dataclass(frozen=True)
class _Header:
    """The entry of a variable in the header."""

    name: str
    dimensions: tuple[str, ...]
    sizes: tuple[int | None, ...]
    attributes: dict[str, Any]
    dtype: np.dtype[Any]
    type_name: str
    begin: int

    @property
    def record(self) -> bool:
        return bool(self.sizes) and self.sizes[0] is None

    @property
    def slab(self) -> int:
        """The number of bytes of one record, or of the variable if it has no records."""
        fixed = self.sizes[1:] if self.record else self.sizes
        return int(np.prod([int(size or 0) for size in fixed], dtype=object)) * self.dtype.itemsize


def _read_variables(
    cursor: _Cursor, version: int, dimensions: list[tuple[str, int | None]]
) -> list[_Header]:
    headers: list[_Header] = []
    for _ in range(cursor.list_header(_VARIABLE, "variables")):
        name = cursor.name()
        identifiers = [cursor.count() for _ in range(cursor.count())]
        if any(identifier >= len(dimensions) for identifier in identifiers):
            raise cursor.fail(f"the variable {name!r} refers to a dimension that does not exist")
        axes = [dimensions[identifier] for identifier in identifiers]
        if any(size is None for _, size in axes[1:]):
            raise cursor.fail(f"the variable {name!r} has the unlimited dimension on an inner axis")
        attributes = _read_attributes(cursor, version)
        dtype, type_name = _type(cursor, version)
        cursor.count()  # vsize: redundant, and wrong for a variable of 4 GiB or more
        headers.append(
            _Header(
                name=name,
                dimensions=tuple(axis for axis, _ in axes),
                sizes=tuple(size for _, size in axes),
                attributes=attributes,
                dtype=dtype,
                type_name=type_name,
                begin=cursor.offset(),
            )
        )
    return headers


def _record_size(headers: list[_Header]) -> int:
    """Return the number of bytes of one record of all record variables together."""
    slabs = [header.slab for header in headers if header.record]
    if len(slabs) == 1:  # a single record variable is stored without padding
        return slabs[0]
    return sum(slab + (-slab % 4) for slab in slabs)


def _record_count(stated: int | None, headers: list[_Header], size: int) -> int:
    """Return the number of records, derived from the size of the file if not stated."""
    if stated is not None:
        return stated
    begins = [header.begin for header in headers if header.record]
    record_size = _record_size(headers)
    if not begins or not record_size:
        return 0
    return max(0, size - min(begins)) // record_size


def _variable(
    header: _Header, records: int, record_size: int, buffer: mmap.mmap, path: Path
) -> Variable:
    shape = tuple(records if size is None else size for size in header.sizes)
    layout = _Layout(header.dtype, shape, header.begin, header.record)
    return Variable(
        name=header.name,
        path=f"/{header.name}",
        dtype=header.dtype.newbyteorder("="),
        shape=shape,
        dimensions=header.dimensions,
        attributes=header.attributes,
        type_name=header.type_name,
        reader=functools.partial(_read, buffer, layout, record_size, header.name, path),
    )


def _read(
    buffer: mmap.mmap, layout: _Layout, record_size: int, name: str, path: Path
) -> np.ndarray[Any, Any]:
    """Read the values of a variable; see `coati.model.Variable.read`."""
    count = int(np.prod(layout.shape, dtype=object)) if layout.shape else 1
    if count == 0:
        return np.empty(layout.shape, dtype=layout.dtype.newbyteorder("="))
    itemsize = layout.dtype.itemsize
    if layout.record:
        slab = count // layout.shape[0] * itemsize
        end = layout.begin + (layout.shape[0] - 1) * record_size + slab
    else:
        end = layout.begin + count * itemsize
    if buffer.closed:
        raise SourceError(f"{path}: the variable {name!r} cannot be read: the file is closed")
    if end > len(buffer):
        raise SourceError(
            f"{path}: damaged netCDF file: the variable {name!r} extends beyond the end of the file"
        )
    if layout.record:
        strides = (record_size, *_strides(layout.shape[1:], itemsize))
        stored: np.ndarray[Any, Any] = np.ndarray(
            layout.shape, layout.dtype, buffer, layout.begin, strides
        )
    else:
        stored = np.ndarray(layout.shape, layout.dtype, buffer, layout.begin)
    return stored.astype(layout.dtype.newbyteorder("="))


def _strides(shape: tuple[int, ...], itemsize: int) -> tuple[int, ...]:
    """Return the strides of a contiguous array of `shape` in row-major order."""
    strides: list[int] = []
    step = itemsize
    for size in reversed(shape):
        strides.append(step)
        step *= size
    return tuple(reversed(strides))
