"""Tables that pandas stores in HDF5 files through PyTables.

PyPSA's `export_to_hdf5` writes every table of a network with
`pandas.HDFStore` in the *table* format. In the file, such a table is a group
with one compound dataset named `table`. The columns of the table are grouped
by type into blocks: a field `values_block_0` holds all columns of one type,
`values_block_1` those of the next, and an attribute of the dataset lists the
names of the columns of each block.

PyTables stores these lists *pickled*. Unpickling data from a file can run
code, so `unpickle` loads them with an unpickler that knows no classes
and no functions at all: it can build text, numbers, lists, tuples and
dictionaries, and refuses everything else. The lists of column names need
nothing more.
"""

from __future__ import annotations

import io
import pickle
from dataclasses import dataclass, field
from typing import Any, Final

import numpy as np

from coati.errors import SourceError
from coati.model import Group, Variable

__all__ = ["Frame", "is_frame", "read_frame", "unpickle"]

_TABLE: Final = "table"
_INDEX: Final = "index"
_BLOCK: Final = "values_block_"

# Resolution of the times of a block of the type datetime64, by the name of the type.
_TIME_UNITS: Final = {
    "datetime64": "ns",
    "datetime64[ns]": "ns",
    "datetime64[us]": "us",
    "datetime64[ms]": "ms",
    "datetime64[s]": "s",
}


@dataclass
class Frame:
    """A table: an index and named columns of equal length.

    Attributes:
        index: The labels of the rows.
        columns: The values of each column, by the name of the column. A
            table of time series has whole numbers as names, the positions
            of the components the series belong to.
    """

    index: np.ndarray[Any, Any]
    columns: dict[str | int, np.ndarray[Any, Any]] = field(default_factory=dict)

    def column(self, name: str | int) -> np.ndarray[Any, Any] | None:
        """Return the values of the column `name`, or `None` if there is none."""
        return self.columns.get(name)

    def __len__(self) -> int:
        return int(self.index.shape[0])


class _NoGlobals(pickle.Unpickler):
    """An unpickler that refuses to load any class or function."""

    def find_class(self, module: str, name: str) -> Any:
        raise pickle.UnpicklingError(f"the pickle refers to {module}.{name}")


def unpickle(data: bytes | str) -> Any:
    """Load a pickle that consists of text, numbers and containers of them.

    Raises:
        SourceError: The pickle is damaged or refers to a class or function.
    """
    raw = data.encode("latin-1") if isinstance(data, str) else data
    try:
        return _NoGlobals(io.BytesIO(raw)).load()
    except Exception as error:  # the unpickler raises many types for damaged input
        raise SourceError(f"a pickled value cannot be loaded: {error}") from error


def is_frame(group: Group) -> bool:
    """Tell whether `group` holds a table that pandas has stored in the table format."""
    table = group.variables.get(_TABLE)
    return (
        table is not None
        and group.attributes.get("pandas_type") == "frame_table"
        and table.dtype.names is not None
        and _INDEX in table.dtype.names
    )


def read_frame(group: Group) -> Frame:
    """Read the table that `group` holds.

    Raises:
        SourceError: The group holds no table or the table is damaged.
    """
    if not is_frame(group):
        raise SourceError(f"{group.path} holds no table of pandas")
    table = group.variables[_TABLE]
    records = table.read()
    missing = group.attributes.get("nan_rep")
    frame = Frame(index=_convert(records[_INDEX], table.attributes.get("index_kind"), None))
    for name in table.dtype.names or ():
        if not name.startswith(_BLOCK):
            continue
        block = records[name].reshape(records.shape[0], -1)
        labels = _labels(table, name, block.shape[1])
        values = _convert(block, table.attributes.get(f"{name}_dtype"), missing)
        for position, label in enumerate(labels):
            frame.columns[label] = values[:, position]
    return frame


def _labels(table: Variable, block: str, width: int) -> list[str | int]:
    """Return the names of the columns of a block."""
    pickled = table.attributes.get(f"{block}_kind")
    if not isinstance(pickled, (str, bytes)):
        raise SourceError(f"{table.path}: the names of the columns of {block} are missing")
    labels = unpickle(pickled)
    if not isinstance(labels, (list, tuple)) or len(labels) != width:
        raise SourceError(f"{table.path}: the names of the columns of {block} are damaged")
    return [label if isinstance(label, int) else str(label) for label in labels]


def _convert(values: np.ndarray[Any, Any], kind: object, missing: object) -> np.ndarray[Any, Any]:
    """Return the values of a block in the type that `kind` names."""
    name = kind if isinstance(kind, str) else ""
    if values.dtype.kind == "S":
        text = np.char.decode(values, "utf-8", "replace").astype(object)
        if isinstance(missing, str):
            text[text == missing] = None
        return text
    if name == "bool":
        return values.astype(bool)
    if name in _TIME_UNITS and values.dtype.kind == "i":
        return values.astype(f"datetime64[{_TIME_UNITS[name]}]")
    return values
