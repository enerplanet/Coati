"""Interpretation of stored values according to the CF conventions.

A netCDF file stores numbers; attributes of the variable say what they mean.
`decode` applies the conventions the modelling frameworks rely on, in
this order:

1. **Characters.** An array of single characters is joined along its last axis
   into text, which is how the classic formats store strings.
2. **Unsigned integers.** `_Unsigned = "true"` reinterprets signed integers.
3. **Missing values.** Elements equal to `_FillValue` or `missing_value` are
   masked. Fill values that the netCDF library applies by default, without the
   attribute, are data, as they are for xarray.
4. **Packed values.** `scale_factor` and `add_offset` unpack to double
   precision.
5. **Truth values.** Integers with the attribute `dtype = "bool"`, the
   convention of xarray, become truth values.
6. **Times.** Numbers with `units` of the form `hours since 2005-01-01` in
   the Gregorian calendar become instants with a resolution of one
   microsecond. A reference time with a zone offset is converted to UTC.

The attributes a step consumes are reported as the *encoding* of the variable,
apart from its descriptive attributes, as xarray does. Whatever cannot be
interpreted safely, such as a calendar without leap years, is left as stored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Final

import numpy as np

from coati.masked import is_masked, mask_of, masked, values_of
from coati.model import Variable

__all__ = ["DecodeOptions", "Decoded", "decode", "decode_values", "parse_time_units"]


@dataclass(frozen=True)
class DecodeOptions:
    """Which conventions `decode` applies; all of them by default."""

    characters: bool = True
    unsigned: bool = True
    missing: bool = True
    packed: bool = True
    booleans: bool = True
    times: bool = True

    @classmethod
    def none(cls) -> DecodeOptions:
        """Return the options that leave the values as stored."""
        return cls(
            characters=False,
            unsigned=False,
            missing=False,
            packed=False,
            booleans=False,
            times=False,
        )


@dataclass
class Decoded:
    """The interpreted values of a variable.

    Attributes:
        values: The values; a masked array if elements are missing.
        type_name: The type of the values, for example `datetime`.
        dimensions: The dimension of each axis of `values`.
        attributes: The attributes that describe the variable.
        encoding: The attributes that decoding has consumed.
    """

    values: np.ndarray[Any, Any]
    type_name: str
    dimensions: tuple[str | None, ...]
    attributes: dict[str, Any] = field(default_factory=dict)
    encoding: dict[str, Any] = field(default_factory=dict)


_DEFAULT: Final = DecodeOptions()

# Length of a unit of time in microseconds. Months and years have no fixed length.
_MICROSECONDS: Final[dict[str, int]] = {
    **dict.fromkeys(("microseconds", "microsecond", "microsec", "microsecs", "us"), 1),
    **dict.fromkeys(
        ("milliseconds", "millisecond", "millisec", "millisecs", "msec", "msecs", "ms"), 1_000
    ),
    **dict.fromkeys(("seconds", "second", "sec", "secs", "s"), 1_000_000),
    **dict.fromkeys(("minutes", "minute", "min", "mins"), 60_000_000),
    **dict.fromkeys(("hours", "hour", "hr", "hrs", "h"), 3_600_000_000),
    **dict.fromkeys(("days", "day", "d"), 86_400_000_000),
}

_GREGORIAN: Final = frozenset({"", "standard", "gregorian", "proleptic_gregorian"})

# The calendars "standard" and "gregorian" switch to the Julian calendar before this day.
_GREGORIAN_START: Final = np.datetime64("1582-10-15", "us")

_UNITS: Final = re.compile(r"^\s*(?P<unit>[A-Za-z]+)\s+since\s+(?P<reference>\S.*?)\s*$", re.I)

_REFERENCE: Final = re.compile(
    r"""^
    (?P<year>\d{1,4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})
    (?:[T\s]+(?P<hour>\d{1,2})
        (?::(?P<minute>\d{1,2})
            (?::(?P<second>\d{1,2})(?P<fraction>\.\d+)?)?
        )?
    )?
    \s*(?P<zone>Z|UTC|[+-]\d{1,2}(?::?\d{2})?)?
    $""",
    re.X | re.I,
)


def decode(variable: Variable, options: DecodeOptions | None = None) -> Decoded:
    """Read `variable` and interpret its values.

    Args:
        variable: The variable to read.
        options: The conventions to apply; all of them if omitted.

    Returns:
        The values with their type, dimensions, attributes and encoding.
    """
    return decode_values(
        variable.read(),
        variable.attributes,
        variable.dimensions,
        variable.type_name,
        options,
    )


def decode_values(
    values: np.ndarray[Any, Any],
    attributes: dict[str, Any],
    dimensions: tuple[str | None, ...],
    type_name: str,
    options: DecodeOptions | None = None,
) -> Decoded:
    """Interpret `values` as `decode` does, without a variable.

    Args:
        values: The stored values.
        attributes: The attributes of the variable.
        dimensions: The dimension of each axis of `values`.
        type_name: The type of the stored values.
        options: The conventions to apply; all of them if omitted.
    """
    options = options or _DEFAULT
    result = Decoded(values, type_name, dimensions, dict(attributes))
    if options.characters:
        _join_characters(result)
    if options.unsigned:
        _reinterpret_unsigned(result)
    if options.missing:
        _mask_missing(result)
    if options.packed:
        _unpack(result)
    if options.booleans:
        _to_truth_values(result)
    if options.times:
        _to_instants(result)
    return result


def parse_time_units(units: object) -> tuple[int, np.datetime64] | None:
    """Parse time units such as `hours since 2005-01-01 00:00:00`.

    Returns:
        The length of the unit in microseconds and the reference time in UTC,
        or `None` if `units` is not of that form, names a unit without a
        fixed length, or names a time that does not exist.
    """
    if not isinstance(units, str):
        return None
    match = _UNITS.match(units)
    if match is None:
        return None
    length = _MICROSECONDS.get(match["unit"].lower())
    reference = _parse_reference(match["reference"])
    if length is None or reference is None:
        return None
    return length, reference


def _parse_reference(text: str) -> np.datetime64 | None:
    match = _REFERENCE.match(text)
    if match is None:
        return None
    parts = {name: int(match[name] or 0) for name in ("hour", "minute", "second")}
    date = f"{int(match['year']):04d}-{int(match['month']):02d}-{int(match['day']):02d}"
    clock = f"{parts['hour']:02d}:{parts['minute']:02d}:{parts['second']:02d}"
    fraction = (match["fraction"] or "")[:7]
    try:
        instant = np.datetime64(f"{date}T{clock}{fraction}", "us")
    except ValueError:
        return None
    if np.isnat(instant):
        return None
    return instant - np.timedelta64(_zone_offset(match["zone"]), "m")


def _zone_offset(zone: str | None) -> int:
    """Return the offset of `zone` from UTC in minutes."""
    if not zone or zone.upper() in ("Z", "UTC"):
        return 0
    digits = zone[1:].replace(":", "")
    hours, minutes = (int(digits), 0) if len(digits) <= 2 else (int(digits[:-2]), int(digits[-2:]))
    offset = hours * 60 + minutes
    return -offset if zone[0] == "-" else offset


def _take(result: Decoded, name: str) -> Any:
    """Move the attribute `name` to the encoding and return its value."""
    value = result.attributes.pop(name)
    result.encoding[name] = value
    return value


def _join_characters(result: Decoded) -> None:
    values = values_of(result.values)
    if result.type_name != "char" or values.ndim == 0 or values.dtype != np.dtype("S1"):
        return
    width = values.shape[-1]
    if width:
        joined = np.ascontiguousarray(values).view(f"S{width}").reshape(values.shape[:-1])
        text = np.char.rstrip(np.char.decode(joined, "utf-8", "replace"), "\x00")
    else:
        text = np.full(values.shape[:-1], "", dtype="U1")
    result.values = np.asarray(text).astype(object)
    result.type_name = "string"
    result.encoding["char_dimension"] = result.dimensions[-1]
    result.dimensions = result.dimensions[:-1]


def _reinterpret_unsigned(result: Decoded) -> None:
    flag = result.attributes.get("_Unsigned")
    if not isinstance(flag, str) or flag.lower() != "true" or result.values.dtype.kind != "i":
        return
    _take(result, "_Unsigned")
    unsigned = np.dtype(f"u{result.values.dtype.itemsize}")
    result.values = result.values.astype(result.values.dtype.newbyteorder("="), copy=False).view(
        unsigned
    )
    result.type_name = unsigned.name
    for name in ("_FillValue", "missing_value"):
        fill = result.attributes.get(name)
        if isinstance(fill, (int, np.integer)) and fill < 0:
            signed = np.array(fill, dtype=f"i{unsigned.itemsize}")
            result.attributes[name] = int(signed.view(unsigned))


def _mask_missing(result: Decoded) -> None:
    values = result.values
    if values.dtype.kind not in "iufOSU":
        return
    markers: list[Any] = []
    for name in ("_FillValue", "missing_value"):
        if name in result.attributes:
            markers.extend(np.atleast_1d(np.asarray(_take(result, name))).tolist())
    if not markers or values.size == 0:
        return
    mask = np.zeros(values.shape, dtype=bool)
    for marker in markers:
        mask |= _equals(values, marker)
    if mask.any():
        result.values = masked(values, mask)


def _equals(values: np.ndarray[Any, Any], marker: Any) -> np.ndarray[Any, Any]:
    """Compare every element with `marker`; two `NaN` are equal here."""
    if isinstance(marker, float) and np.isnan(marker):
        if values.dtype.kind == "f":
            return np.asarray(np.isnan(values), dtype=bool)
        return np.zeros(values.shape, dtype=bool)
    if values.dtype.kind in "iuf" and isinstance(marker, str):
        return np.zeros(values.shape, dtype=bool)
    try:
        with np.errstate(invalid="ignore"):
            return np.asarray(values == marker, dtype=bool)
    except (TypeError, ValueError, OverflowError):
        return np.zeros(values.shape, dtype=bool)


def _unpack(result: Decoded) -> None:
    attributes = result.attributes
    if result.values.dtype.kind not in "iuf":
        return
    if "scale_factor" not in attributes and "add_offset" not in attributes:
        return
    factors = {}
    for name, neutral in (("scale_factor", 1.0), ("add_offset", 0.0)):
        value = attributes.get(name, neutral)
        if not isinstance(value, (int, float, np.integer, np.floating)) or isinstance(value, bool):
            return
        factors[name] = float(value)
    for name in ("scale_factor", "add_offset"):
        if name in attributes:
            _take(result, name)
    result.values = result.values * factors["scale_factor"] + factors["add_offset"]
    result.type_name = "float64"


def _to_truth_values(result: Decoded) -> None:
    if result.attributes.get("dtype") != "bool" or result.values.dtype.kind not in "iu":
        return
    _take(result, "dtype")
    result.values = result.values.astype(bool)
    result.type_name = "bool"


def _to_instants(result: Decoded) -> None:
    values = result.values
    if values.dtype.kind not in "iuf" or "units" not in result.attributes:
        return
    parsed = parse_time_units(result.attributes["units"])
    calendar = result.attributes.get("calendar", "")
    if parsed is None or not isinstance(calendar, str) or calendar.lower() not in _GREGORIAN:
        return
    length, reference = parsed
    instants = _instants(values, length, reference)
    if instants is None:
        return
    if calendar.lower() != "proleptic_gregorian" and _before_gregorian(instants, reference):
        return
    _take(result, "units")
    if "calendar" in result.attributes:
        _take(result, "calendar")
    result.values = instants
    result.type_name = "datetime"


def _instants(
    values: np.ndarray[Any, Any], length: int, reference: np.datetime64
) -> np.ndarray[Any, Any] | None:
    """Return `reference + values * length`, or `None` if that leaves the range of time."""
    data = values_of(values)
    hidden = mask_of(values) if is_masked(values) else None
    if data.dtype.kind == "f":
        missing = ~np.isfinite(data)
        hidden = missing if hidden is None else hidden | missing
        data = np.where(missing, 0.0, data)
    limit = (np.iinfo(np.int64).max - abs(int(reference.astype(np.int64)))) // length
    if data.size and float(np.abs(data.astype(np.float64)).max()) >= float(limit):
        return None
    if data.dtype.kind == "f":
        offsets = np.rint(data.astype(np.float64) * length).astype(np.int64)
    else:
        offsets = data.astype(np.int64) * length
    instants = reference + offsets.astype("timedelta64[us]")
    if hidden is not None and hidden.any():
        instants[hidden] = np.datetime64("NaT", "us")
    return np.asarray(instants)


def _before_gregorian(instants: np.ndarray[Any, Any], reference: np.datetime64) -> bool:
    known = instants[~np.isnat(instants)]
    earliest = min(reference, known.min()) if known.size else reference
    return bool(earliest < _GREGORIAN_START)
