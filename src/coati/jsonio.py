"""Strict JSON output for documents that hold NumPy data.

The module writes JSON as [RFC 8259](https://www.rfc-editor.org/rfc/rfc8259)
defines it. The encoder of the standard
library differs from that in one way that matters for model results: it writes
`NaN` and `Infinity`, which are not JSON and which most parsers reject.
Result files are full of both, so every number passes a policy here
(`JsonOptions.non_finite`) before it is written.

Documents are plain dictionaries and lists. Their leaves may be Python scalars,
NumPy scalars, NumPy arrays of any dimension and masked arrays. Any part of a
document may also be an object with a method `__coati_json__`; the encoder
calls it when it reaches the object and writes what it returns. This is how a
large file is converted one variable at a time: the values of a variable are
read when they are written and released afterwards.

The output is produced as a stream of text chunks (`iterencode`). Arrays
are formatted in bulk by the C encoder of the standard library; an array of
numbers is written on one line even in an indented document, which keeps a time
series readable and the file small.
"""

from __future__ import annotations

import base64
import contextlib
import datetime as dt
import json
import math
import os
import tempfile
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Final, Literal, cast

import numpy as np

from coati.errors import EncodingError
from coati.masked import is_masked, mask_of, masked, values_of

__all__ = [
    "NON_FINITE_POLICIES",
    "JsonOptions",
    "dump",
    "dumps",
    "iterencode",
    "write_file",
]

NonFinite = Literal["null", "string", "error"]

#: The values that `JsonOptions.non_finite` accepts.
NON_FINITE_POLICIES: Final[tuple[str, ...]] = ("null", "string", "error")

# Elements of a one-dimensional array that are formatted and emitted together.
_CHUNK: Final = 1 << 16

# Whole numbers up to this magnitude are exact in double precision.
_EXACT: Final = 2.0**53

_Path = tuple[str | int, ...]


@dataclass(frozen=True)
class JsonOptions:
    """How a document is written.

    Attributes:
        indent: Spaces per nesting level, or `None` for the most compact
            output without any whitespace.
        non_finite: What becomes of `NaN` and the infinities. `"null"`
            writes `null`; `"string"` writes the strings `"NaN"`,
            `"Infinity"` and `"-Infinity"`, which keeps the distinction;
            `"error"` refuses the document.
        decimals: Decimal places floating-point numbers are rounded to, or
            `None` to write every number with the digits needed to read it
            back unchanged. Rounding also turns negative zero into zero. A
            number so large that it has no digits at the places in question
            is written as it is.
        sort_keys: Write the keys of every object in sorted order instead of
            the order of the document.
        ensure_ascii: Escape every character outside ASCII.
    """

    indent: int | None = 2
    non_finite: NonFinite = "null"
    decimals: int | None = None
    sort_keys: bool = False
    ensure_ascii: bool = False

    def __post_init__(self) -> None:
        if self.indent is not None and (isinstance(self.indent, bool) or self.indent < 0):
            raise ValueError(f"indent must be a non-negative integer or None, not {self.indent!r}")
        if self.non_finite not in NON_FINITE_POLICIES:
            choices = ", ".join(NON_FINITE_POLICIES)
            raise ValueError(f"non_finite must be one of {choices}, not {self.non_finite!r}")
        if self.decimals is not None and (isinstance(self.decimals, bool) or self.decimals < 0):
            raise ValueError(
                f"decimals must be a non-negative integer or None, not {self.decimals!r}"
            )


_DEFAULT_OPTIONS: Final = JsonOptions()


def iterencode(document: object, options: JsonOptions | None = None) -> Iterator[str]:
    """Encode `document` and yield the JSON text in chunks.

    Args:
        document: The value to encode.
        options: How to write it; the defaults of `JsonOptions` if omitted.

    Yields:
        Pieces of the JSON text, in order. They do not end with a newline.

    Raises:
        EncodingError: A value cannot be written as JSON. The message names the
            position of the value in the document.
    """
    return _Encoder(options or _DEFAULT_OPTIONS).encode(document)


def dumps(document: object, options: JsonOptions | None = None) -> str:
    """Encode `document` and return the JSON text.

    See `iterencode` for the arguments and the errors.
    """
    return "".join(iterencode(document, options))


def dump(document: object, stream: IO[str], options: JsonOptions | None = None) -> None:
    """Encode `document` and write it to `stream`, followed by a newline.

    See `iterencode` for the arguments and the errors.
    """
    for chunk in iterencode(document, options):
        stream.write(chunk)
    stream.write("\n")


def write_file(
    document: object, path: str | os.PathLike[str], options: JsonOptions | None = None
) -> None:
    """Encode `document` into the file `path`, replacing it in one step.

    The text is written to a temporary file in the directory of `path` and
    moved into place once it is complete. A reader of `path` therefore sees
    the previous content or the new one, never a part, and a conversion that
    fails leaves an existing file untouched. The file is encoded as UTF-8 and
    ends with a newline.

    Raises:
        EncodingError: A value cannot be written as JSON.
        OSError: The file cannot be written.
    """
    target = Path(path)
    try:
        handle, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    except OSError as error:  # name the file that was to be written, not the temporary one
        raise type(error)(error.errno, error.strerror, str(target)) from None
    temporary = Path(name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            dump(document, stream, options)
        _copy_mode(target, temporary)
        temporary.replace(target)
    except BaseException:
        with contextlib.suppress(OSError):
            temporary.unlink()
        raise


def _copy_mode(target: Path, temporary: Path) -> None:
    """Give `temporary` the permissions a plainly created `target` would have."""
    try:
        mode = target.stat().st_mode & 0o777
    except OSError:
        umask = os.umask(0)
        os.umask(umask)
        mode = 0o666 & ~umask
    with contextlib.suppress(OSError):
        temporary.chmod(mode)


class _Encoder:
    """Turns a document into JSON text for one set of options."""

    def __init__(self, options: JsonOptions) -> None:
        self._options = options
        self._pretty = options.indent is not None
        self._step = " " * (options.indent or 0)
        self._item_separator = ", " if self._pretty else ","
        self._key_separator = ": " if self._pretty else ":"
        self._native = json.JSONEncoder(
            ensure_ascii=options.ensure_ascii,
            allow_nan=False,
            separators=(self._item_separator, self._key_separator),
        )

    def encode(self, document: object) -> Iterator[str]:
        """Yield the text of `document`."""
        return self._value(document, 0, ())

    # -- dispatch ---------------------------------------------------------------------------

    def _value(self, value: object, level: int, path: _Path) -> Iterator[str]:
        text = self._scalar(value, path)
        if text is not None:
            yield text
        elif isinstance(value, Mapping):
            yield from self._object(value, level, path)
        elif isinstance(value, np.ndarray):
            yield from self._array(value, level, path)
        elif isinstance(value, (list, tuple)):
            yield from self._sequence(value, level, path)
        elif isinstance(value, np.void):
            yield from self._object(cast("dict[str, object]", _element(value)), level, path)
        elif isinstance(value, (complex, np.complexfloating)):
            yield from self._sequence([value.real, value.imag], level, path)
        elif hasattr(value, "__coati_json__"):
            yield from self._value(value.__coati_json__(), level, path)
        else:
            raise EncodingError(
                f"{_locate(path)}: a value of type {type(value).__name__} cannot be written as JSON"
            )

    def _scalar(self, value: object, path: _Path) -> str | None:
        """Return the text of a scalar, or `None` if `value` is a container."""
        if value is None or value is np.ma.masked:
            return "null"
        if isinstance(value, (bool, np.bool_)):
            return "true" if value else "false"
        if isinstance(value, str):
            return self._native.encode(str(value))
        if isinstance(value, np.timedelta64):
            raise EncodingError(
                f"{_locate(path)}: a value of type numpy.{value.dtype} cannot be written as JSON"
            )
        if isinstance(value, (int, np.integer)):
            return str(int(value))
        if isinstance(value, float):
            return self._float(value, path)
        if isinstance(value, np.floating):
            return self._float(_widen(value), path)
        if isinstance(value, (bytes, np.bytes_)):
            return self._native.encode(_text(bytes(value)))
        if isinstance(value, np.datetime64):
            return self._native.encode(_instant(value)) if not np.isnat(value) else "null"
        if isinstance(value, (dt.datetime, dt.date, dt.time)):
            return self._native.encode(value.isoformat())
        if isinstance(value, np.void):
            return None if value.dtype.names else self._native.encode(_opaque(value))
        if isinstance(value, np.complexfloating):
            return None
        if isinstance(value, np.generic):
            raise EncodingError(
                f"{_locate(path)}: a value of type numpy.{value.dtype} cannot be written as JSON"
            )
        return None

    def _float(self, value: float, path: _Path) -> str:
        if math.isfinite(value):
            if self._options.decimals is not None:
                value = float(_round(np.float64(value), self._options.decimals))
            return float.__repr__(value)
        policy = self._options.non_finite
        if policy == "null":
            return "null"
        if policy == "string":
            return f'"{_non_finite_name(value)}"'
        raise EncodingError(
            f"{_locate(path)}: {_non_finite_name(value)} is not a JSON number"
            " (choose the non-finite policy 'null' or 'string' to write it)"
        )

    # -- containers -------------------------------------------------------------------------

    def _object(self, value: Mapping[Any, object], level: int, path: _Path) -> Iterator[str]:
        items: Iterable[tuple[Any, object]] = value.items()
        for key in value:
            if not isinstance(key, str):
                raise EncodingError(
                    f"{_locate(path)}: the key {key!r} of type {type(key).__name__} is not a string"
                )
        if self._options.sort_keys:
            items = sorted(items, key=lambda item: item[0])
        first = True
        inner = self._break(level + 1)
        for key, item in items:
            yield "{" + inner if first else "," + inner
            first = False
            yield self._native.encode(str(key)) + self._key_separator
            yield from self._value(item, level + 1, (*path, str(key)))
        yield "{}" if first else self._break(level) + "}"

    def _sequence(self, value: Sequence[object], level: int, path: _Path) -> Iterator[str]:
        if not value:
            yield "[]"
            return
        inline = self._inline(value)
        if inline is not None:
            yield inline
            return
        texts = [self._scalar(item, (*path, index)) for index, item in enumerate(value)]
        if all(text is not None for text in texts):
            yield "[" + self._item_separator.join(cast("list[str]", texts)) + "]"
            return
        inner = self._break(level + 1)
        for index, item in enumerate(value):
            yield ("[" if index == 0 else ",") + inner
            yield from self._value(item, level + 1, (*path, index))
        yield self._break(level) + "]"

    def _inline(self, value: Sequence[object]) -> str | None:
        """Encode a list of built-in scalars with the C encoder, if it is one."""
        if self._options.decimals is not None:
            return None
        for item in value:
            if item is not None and type(item) not in (bool, int, float, str):
                return None
        try:
            return self._native.encode(list(value))
        except ValueError:  # a non-finite number: the policy decides, element by element
            return None

    def _break(self, level: int) -> str:
        return "\n" + self._step * level if self._pretty else ""

    # -- arrays -----------------------------------------------------------------------------

    def _array(self, array: np.ndarray[Any, Any], level: int, path: _Path) -> Iterator[str]:
        if array.dtype.kind == "c":
            array = _pairs(array)
        if array.ndim == 0:
            yield from self._value(_item(array), level, path)
        elif array.ndim == 1:
            yield from self._row(array, level, path)
        elif array.shape[0] == 0:
            yield "[]"
        else:
            inner = self._break(level + 1)
            for index in range(array.shape[0]):
                yield ("[" if index == 0 else ",") + inner
                yield from self._array(array[index], level + 1, (*path, index))
            yield self._break(level) + "]"

    def _row(self, row: np.ndarray[Any, Any], level: int, path: _Path) -> Iterator[str]:
        if row.dtype.kind == "O" or row.dtype.names:
            yield from self._sequence(_elements(row), level, path)
            return
        if row.size == 0:
            yield "[]"
            return
        yield "["
        for start in range(0, row.size, _CHUNK):
            if start:
                yield self._item_separator
            native = self._native_row(row[start : start + _CHUNK], start, path)
            yield self._native.encode(native)[1:-1]
        yield "]"

    def _native_row(self, row: np.ndarray[Any, Any], start: int, path: _Path) -> list[Any]:
        """Convert a one-dimensional array to built-in values the C encoder accepts."""
        mask = mask_of(row) if is_masked(row) else None
        data = values_of(row)
        kind = data.dtype.kind
        if kind == "f":
            return self._floats(data, mask, start, path)
        if kind == "M":
            values = _instants(data)
        elif kind == "S":
            values = np.char.decode(data, "utf-8", "replace").astype(object)
        elif kind == "V":
            values = np.array([_opaque(item) for item in data], dtype=object)
        elif kind in "biuU":
            values = data.astype(object) if mask is not None and mask.any() else data
        else:
            raise EncodingError(
                f"{_locate(path)}: an array of type {data.dtype} cannot be written as JSON"
            )
        if mask is not None and mask.any():
            values = values.astype(object)
            values[mask] = None
        return cast("list[Any]", values.tolist())

    def _floats(
        self,
        data: np.ndarray[Any, Any],
        mask: np.ndarray[Any, Any] | None,
        start: int,
        path: _Path,
    ) -> list[Any]:
        values = _widen_array(data)
        if self._options.decimals is not None:
            values = _round(values, self._options.decimals)
        finite = np.isfinite(values)
        missing = mask if mask is not None and mask.any() else None
        if finite.all() and missing is None:
            return cast("list[Any]", values.tolist())
        result = values.astype(object)
        self._replace_non_finite(result, values, finite, missing, start, path)
        if missing is not None:
            result[missing] = None
        return cast("list[Any]", result.tolist())

    def _replace_non_finite(
        self,
        result: np.ndarray[Any, Any],
        values: np.ndarray[Any, Any],
        finite: np.ndarray[Any, Any],
        missing: np.ndarray[Any, Any] | None,
        start: int,
        path: _Path,
    ) -> None:
        policy = self._options.non_finite
        if policy == "null":
            result[~finite] = None
        elif policy == "string":
            result[np.isnan(values)] = "NaN"
            result[np.isposinf(values)] = "Infinity"
            result[np.isneginf(values)] = "-Infinity"
        else:
            offending = ~finite if missing is None else ~finite & ~missing
            if offending.any():
                index = int(np.flatnonzero(offending)[0])
                name = _non_finite_name(float(values[index]))
                raise EncodingError(
                    f"{_locate((*path, start + index))}: {name} is not a JSON number"
                    " (choose the non-finite policy 'null' or 'string' to write it)"
                )


# -- conversions ----------------------------------------------------------------------------


def _round(values: Any, decimals: int) -> Any:
    """Round to `decimals` places, a number and an array of numbers alike.

    Rounding multiplies by a power of ten. For a number whose product is too
    large to be exact, that would change digits which rounding is not meant to
    touch; such a number has no digits at the places in question and is kept.
    """
    with np.errstate(invalid="ignore", over="ignore"):
        exact = np.abs(values) < _EXACT / 10.0**decimals
        return np.where(exact, np.round(values, decimals) + 0.0, values)


def _non_finite_name(value: float) -> str:
    if math.isnan(value):
        return "NaN"
    return "Infinity" if value > 0 else "-Infinity"


def _widen(value: np.floating[Any]) -> float:
    """Return `value` as the double that prints like it.

    A single-precision `0.1` converted to double precision is
    `0.10000000149011612`. Going through the shortest text that identifies
    the number in its own precision yields the double `0.1` instead.
    """
    if value.dtype.itemsize >= 8:
        return float(value)
    return float(str(value))


def _widen_array(data: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    """Return `data` in double precision; see `_widen`."""
    if data.dtype == np.float64:
        return data
    if data.dtype.itemsize > 8:  # extended precision has no JSON counterpart
        return data.astype(np.float64)
    return cast("np.ndarray[Any, Any]", data.astype(str).astype(np.float64))


def _pairs(array: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    """Return complex numbers as pairs of their real and imaginary part."""
    pairs = np.stack([array.real, array.imag], axis=-1)
    if is_masked(array):
        missing = np.repeat(mask_of(array)[..., np.newaxis], 2, axis=-1)
        return masked(pairs, missing)
    return pairs


def _text(value: bytes) -> str:
    return value.decode("utf-8", "replace")


def _opaque(value: np.void) -> str:
    return base64.b64encode(value.tobytes()).decode("ascii")


def _instant(value: np.datetime64) -> str:
    return str(_instants(np.asarray([value]))[0])


def _instants(data: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    """Format instants as ISO 8601 text; an instant that is not a time becomes `None`."""
    unit = np.datetime_data(data.dtype)[0]
    if unit in ("Y", "M", "W", "D"):
        text = np.datetime_as_string(data, unit="D")
    else:
        seconds = data.astype("datetime64[s]")
        whole = (seconds == data) | np.isnat(data)
        text = np.datetime_as_string(seconds if whole.all() else data)
    result = text.astype(object)
    result[np.isnat(data)] = None
    return cast("np.ndarray[Any, Any]", result)


def _item(array: np.ndarray[Any, Any]) -> object:
    """Return the only element of a zero-dimensional array."""
    if is_masked(array) and mask_of(array).any():
        return None
    return _element(array[()])


def _elements(row: np.ndarray[Any, Any]) -> list[object]:
    """Return the elements of an array of objects or records, one by one."""
    if is_masked(row):
        mask = mask_of(row)
        data = values_of(row)
        return [None if _hidden(mask[i]) else _element(data[i]) for i in range(row.size)]
    return [_element(row[i]) for i in range(row.size)]


def _hidden(flag: Any) -> bool:
    return bool(np.all(flag.tolist() if isinstance(flag, np.void) else flag))


def _element(value: object) -> object:
    """Return a record as a dictionary and anything else unchanged."""
    if isinstance(value, np.void) and value.dtype.names:
        return {name: _field(value[name]) for name in value.dtype.names}
    return value


def _field(value: object) -> object:
    if isinstance(value, np.ndarray) and value.dtype.names:
        return [_element(item) for item in value.ravel()] if value.ndim else _element(value[()])
    return _element(value)


def _locate(path: _Path) -> str:
    """Render a position in the document, for example `$.dispatch.pv[12]`."""
    text = "$"
    for part in path:
        if isinstance(part, int):
            text += f"[{part}]"
        elif part.isidentifier():
            text += f".{part}"
        else:
            text += f"[{json.dumps(part)}]"
    return text
