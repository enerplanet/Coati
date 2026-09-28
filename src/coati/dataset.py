"""The dataset document: everything a file holds, whatever wrote it.

Where the results document answers what a model says, the dataset document
answers what is in the file: every group, dimension, variable and attribute,
with the values. It needs no knowledge of a framework and reads any netCDF or
HDF5 file. Its layout follows the data model of netCDF:

```text
{
  "attributes": {...},
  "dimensions": {"timesteps": {"size": 48, "unlimited": false}},
  "variables": {
    "flow_cap": {
      "dtype": "float64",
      "dimensions": ["nodes", "techs"],
      "shape": [5, 8],
      "attributes": {...},
      "encoding": {"_FillValue": null},
      "data": [[...], ...]
    }
  },
  "groups": {"results": {...}}
}
```

By default the values are interpreted according to the CF conventions (see
`coati.cf`): times become ISO 8601 text, missing values `null`. The
attributes that the interpretation consumes are listed as the `encoding` of
the variable, apart from its descriptive `attributes`. With
`decode=False` the values and the attributes are those of the file.

The values of a variable are read when the variable is written, so a document
can describe a file that is larger than the memory. The file has to stay open
until the document has been written.
"""

from __future__ import annotations

import datetime as dt
import fnmatch
import json
from dataclasses import dataclass
from typing import Any, Final

import numpy as np

from coati import cf
from coati._version import __version__
from coati.errors import CoatiError
from coati.model import Dataset, Group, Variable

__all__ = ["SCHEMA_VERSION", "DumpOptions", "build_document"]

#: The version of the layout of the dataset document.
SCHEMA_VERSION: Final = "1.0"


@dataclass(frozen=True)
class DumpOptions:
    """The choices a caller has when a dataset document is made.

    Attributes:
        data: Whether the values of the variables are part of the document.
            Without them the document describes the structure of the file.
        decode: Whether the values are interpreted according to the CF conventions.
        decode_text: Whether an attribute that holds a JSON or YAML document
            is reported as that document instead of as text. YAML needs PyYAML.
        max_elements: The largest number of elements of a variable whose
            values are part of the document; `None` for no limit.
        variables: Patterns in the style of the shell, such as
            `/results/flow_*`, that select variables by their path or
            name; every variable if empty.
    """

    data: bool = True
    decode: bool = True
    decode_text: bool = False
    max_elements: int | None = None
    variables: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.max_elements is not None and self.max_elements < 0:
            raise ValueError(f"max_elements must not be negative, not {self.max_elements!r}")

    def selects(self, variable: Variable) -> bool:
        """Tell whether `variable` is part of the document."""
        if not self.variables:
            return True
        return any(
            fnmatch.fnmatchcase(variable.path, pattern)
            or fnmatch.fnmatchcase(variable.name, pattern)
            for pattern in self.variables
        )


def build_document(
    dataset: Dataset, options: DumpOptions | None = None, *, lazy: bool = True
) -> dict[str, Any]:
    """Describe `dataset` as a dictionary that can be written as JSON.

    Args:
        dataset: The open file.
        options: The choices of the caller; the defaults if omitted.
        lazy: Whether the values of a variable are read when the variable is
            written. If so, the dataset has to stay open until the document
            has been written, and the entries of the variables are objects
            that `coati.jsonio` understands. If not, the document
            consists of dictionaries, lists and arrays only.

    Raises:
        CoatiError: `decode_text` meets YAML and PyYAML is not installed.
    """
    options = options or DumpOptions()
    builder = _Builder(options, lazy)
    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "format": dataset.format,
        **builder.group(dataset),
    }
    document["warnings"] = list(dataset.warnings)
    document["metadata"] = {
        "generator": "coati",
        "generator_version": __version__,
        "source": {"name": dataset.source.name, "format": dataset.format},
        "properties": dict(dataset.properties),
    }
    return document


class _Builder:
    def __init__(self, options: DumpOptions, lazy: bool) -> None:
        self._options = options
        self._lazy = lazy
        self._cf = cf.DecodeOptions() if options.decode else cf.DecodeOptions.none()

    def group(self, group: Group) -> dict[str, Any]:
        return {
            "attributes": self.attributes(group.attributes),
            "dimensions": {
                name: {"size": dimension.size, "unlimited": dimension.unlimited}
                for name, dimension in group.dimensions.items()
            },
            "variables": {
                name: self.variable(variable)
                for name, variable in group.variables.items()
                if self._options.selects(variable)
            },
            "groups": {name: self.group(child) for name, child in group.groups.items()},
        }

    def variable(self, variable: Variable) -> Any:
        entry = _Entry(variable, self)
        return entry if self._lazy else entry.__coati_json__()

    def attributes(self, attributes: dict[str, Any]) -> dict[str, Any]:
        if not self._options.decode_text:
            return dict(attributes)
        return {name: _parse_text(value) for name, value in attributes.items()}

    def describe(self, variable: Variable) -> dict[str, Any]:
        """Return the entry of a variable: its description and, if wanted, its values."""
        wanted = self._options.data and (
            self._options.max_elements is None or variable.size <= self._options.max_elements
        )
        if wanted:
            decoded = cf.decode(variable, self._cf)
        else:  # interpret an empty array: the description does not depend on the values
            empty = np.empty((0,) * variable.ndim, dtype=variable.dtype)
            decoded = cf.decode_values(
                empty, variable.attributes, variable.dimensions, variable.type_name, self._cf
            )
        shape = decoded.values.shape if wanted else _shape(variable, decoded)
        entry: dict[str, Any] = {
            "dtype": decoded.type_name,
            "dimensions": list(decoded.dimensions),
            "shape": list(shape),
            "attributes": self.attributes(decoded.attributes),
        }
        if decoded.encoding:
            entry["encoding"] = decoded.encoding
        if variable.enumeration is not None:
            entry["enumeration"] = variable.enumeration
        if wanted:
            entry["data"] = decoded.values
        elif self._options.data:
            entry["data_omitted"] = True
        return entry


def _shape(variable: Variable, decoded: cf.Decoded) -> tuple[int, ...]:
    """Return the shape of the interpreted values of a variable that has not been read."""
    return variable.shape[: len(decoded.dimensions)]


class _Entry:
    """The entry of a variable, made when it is written."""

    __slots__ = ("_builder", "_variable")

    def __init__(self, variable: Variable, builder: _Builder) -> None:
        self._variable = variable
        self._builder = builder

    def __coati_json__(self) -> dict[str, Any]:
        return self._builder.describe(self._variable)

    def __repr__(self) -> str:
        return f"<entry of {self._variable.path}>"


def _parse_text(value: Any) -> Any:
    """Return the document that the text `value` holds, or `value` itself."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text[:1] in ("{", "["):
        try:
            return json.loads(text)
        except ValueError:
            return value
    if "\n" not in text or ":" not in text:
        return value
    parsed = _parse_yaml(text)
    return _plain(parsed) if isinstance(parsed, (dict, list)) else value


def _parse_yaml(text: str) -> Any:
    try:
        import yaml
    except ImportError:
        raise CoatiError(
            "reading YAML needs PyYAML; install it with: pip install 'enerplanet-coati[yaml]'"
        ) from None
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        return None


def _plain(value: Any) -> Any:
    """Return what a YAML parser produced in terms that JSON has."""
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_plain(item) for item in value), key=str)
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value
