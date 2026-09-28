"""The description of a data file that every reader produces.

A file is a tree of `Group` objects. A group holds attributes,
dimensions, variables and further groups; the root of the tree is a
`Dataset`, which also knows the file and its format. The model is that
of netCDF, which HDF5 files fit as well: an HDF5 dataset is a variable whose
axes may have no dimension.

The structure of a file is read when it is opened, the values of a variable
when `Variable.read` is called. A dataset therefore has to stay open while
its variables are read; use it as a context manager.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Any

import numpy as np

__all__ = ["Dataset", "Dimension", "Group", "Variable"]

#: An attribute value: text, a number, a truth value, nothing, a list of texts or an array.
AttributeValue = Any


@dataclass(frozen=True)
class Dimension:
    """A named axis.

    Attributes:
        name: The name, unique within the group that defines the dimension.
        size: The current number of elements.
        unlimited: Whether the dimension can grow.
    """

    name: str
    size: int
    unlimited: bool = False


class Variable:
    """A named array with attributes.

    Attributes:
        name: The name within the group.
        path: The absolute path in the file, for example `/results/flow_cap`.
        dtype: The type of the stored values. Text is reported as the NumPy
            type `object`, whatever the length and encoding in the file.
        shape: The extent of each axis.
        dimensions: The name of the dimension of each axis; `None` for an
            axis without one, which occurs in HDF5 files that are not netCDF.
        attributes: The attributes, in the order of the file.
        type_name: The type as the documents report it, for example
            `float64` or `string`.
        enumeration: For a variable of an enumerated type, the name of each
            value; `None` otherwise.
    """

    __slots__ = (
        "_reader",
        "attributes",
        "dimensions",
        "dtype",
        "enumeration",
        "name",
        "path",
        "shape",
        "type_name",
    )

    def __init__(
        self,
        *,
        name: str,
        path: str,
        dtype: np.dtype[Any],
        shape: tuple[int, ...],
        dimensions: tuple[str | None, ...],
        attributes: dict[str, AttributeValue],
        type_name: str,
        reader: Callable[[], np.ndarray[Any, Any]],
        enumeration: dict[str, int] | None = None,
    ) -> None:
        self.name = name
        self.path = path
        self.dtype = dtype
        self.shape = shape
        self.dimensions = dimensions
        self.attributes = attributes
        self.type_name = type_name
        self.enumeration = enumeration
        self._reader = reader

    @property
    def size(self) -> int:
        """The number of elements."""
        return int(np.prod(self.shape, dtype=np.int64)) if self.shape else 1

    @property
    def ndim(self) -> int:
        """The number of axes."""
        return len(self.shape)

    def read(self) -> np.ndarray[Any, Any]:
        """Read the stored values.

        The values are those of the file: nothing is masked, scaled or turned
        into times. Text is returned as `str` objects. See
        `coati.cf.decode` for the interpreted values.
        """
        return self._reader()

    def __repr__(self) -> str:
        axes = ", ".join(
            f"{name or '?'}: {size}" for name, size in zip(self.dimensions, self.shape, strict=True)
        )
        return f"<Variable {self.path} {self.type_name} ({axes})>"


@dataclass(eq=False)
class Group:
    """A node of the tree: attributes, dimensions, variables and further groups.

    Attributes:
        name: The name within the parent; the empty string for the root.
        path: The absolute path in the file; `/` for the root.
        attributes: The attributes of the group, in the order of the file.
        dimensions: The dimensions the group defines, by name.
        variables: The variables of the group, by name.
        groups: The groups within the group, by name.
        parent: The enclosing group; `None` for the root.
    """

    name: str
    path: str
    attributes: dict[str, AttributeValue] = field(default_factory=dict)
    dimensions: dict[str, Dimension] = field(default_factory=dict)
    variables: dict[str, Variable] = field(default_factory=dict)
    groups: dict[str, Group] = field(default_factory=dict)
    parent: Group | None = field(default=None, repr=False)

    def get(self, path: str) -> Group | Variable | None:
        """Return the group or variable at `path`, or `None` if there is none.

        Args:
            path: Names separated by `/`. A leading `/` starts at the root
                of the file, otherwise the path is relative to this group.
        """
        node: Group = self.root if path.startswith("/") else self
        names = [name for name in path.split("/") if name]
        for index, name in enumerate(names):
            last = index == len(names) - 1
            if last and name in node.variables:
                return node.variables[name]
            if name not in node.groups:
                return None
            node = node.groups[name]
        return node

    def variable(self, path: str) -> Variable | None:
        """Return the variable at `path`, or `None` if there is none."""
        found = self.get(path)
        return found if isinstance(found, Variable) else None

    def group(self, path: str) -> Group | None:
        """Return the group at `path`, or `None` if there is none."""
        found = self.get(path)
        return found if isinstance(found, Group) else None

    def dimension(self, name: str) -> Dimension | None:
        """Return the dimension `name` visible here: of this group or of an enclosing one."""
        node: Group | None = self
        while node is not None:
            if name in node.dimensions:
                return node.dimensions[name]
            node = node.parent
        return None

    @property
    def root(self) -> Group:
        """The root of the tree this group belongs to."""
        node = self
        while node.parent is not None:
            node = node.parent
        return node

    def walk(self) -> Iterator[Group]:
        """Yield this group and every group below it, parents first."""
        yield self
        for child in self.groups.values():
            yield from child.walk()

    def __contains__(self, path: object) -> bool:
        return isinstance(path, str) and self.get(path) is not None


@dataclass(eq=False)
class Dataset(Group):
    """The root group of a file, together with what is known about the file.

    Attributes:
        source: The path of the file.
        format: The format: `netcdf4`, `hdf5`, `netcdf3-classic`,
            `netcdf3-64bit-offset` or `netcdf3-64bit-data`.
        properties: What the file says about the software that wrote it.
        warnings: What the reader could not represent, as sentences for a person.
    """

    source: Path = field(default_factory=Path)
    format: str = ""
    properties: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    _closer: Callable[[], None] | None = field(default=None, repr=False)

    def close(self) -> None:
        """Close the file. Variables cannot be read afterwards."""
        closer, self._closer = self._closer, None
        if closer is not None:
            closer()

    @property
    def closed(self) -> bool:
        """Whether `close` has been called."""
        return self._closer is None

    def __enter__(self) -> Dataset:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
