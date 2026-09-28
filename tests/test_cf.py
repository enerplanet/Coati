"""Interpreting stored values according to the CF conventions."""

from __future__ import annotations

import datetime as dt
from typing import Any

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from coati import cf
from coati.cf import DecodeOptions, decode_values, parse_time_units


def decoded(
    values: Any, attributes: dict[str, Any], type_name: str = "", **options: bool
) -> cf.Decoded:
    array = np.asarray(values)
    dimensions = tuple(f"d{axis}" for axis in range(array.ndim))
    chosen = DecodeOptions(**options) if options else None
    return decode_values(array, attributes, dimensions, type_name or array.dtype.name, chosen)


def instants(*texts: str) -> np.ndarray:
    return np.array(texts, dtype="datetime64[us]")


# -- times ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("units", "length", "reference"),
    [
        ("hours since 2005-01-01 00:00:00", 3_600_000_000, "2005-01-01T00:00:00"),
        ("hours since 2005-01-01", 3_600_000_000, "2005-01-01"),
        ("Hours Since 2005-01-01T06:30", 3_600_000_000, "2005-01-01T06:30"),
        ("days since 1970-01-01", 86_400_000_000, "1970-01-01"),
        ("minutes since 2005-1-1 0:0:0", 60_000_000, "2005-01-01"),
        ("seconds since 2005-01-01 00:00:00.5", 1_000_000, "2005-01-01T00:00:00.5"),
        ("milliseconds since 2005-01-01", 1_000, "2005-01-01"),
        ("microseconds since 2005-01-01", 1, "2005-01-01"),
        ("h since 2005-01-01", 3_600_000_000, "2005-01-01"),
        ("  days   since   2005-01-01  ", 86_400_000_000, "2005-01-01"),
        ("hours since 2005-01-01 00:00:00 UTC", 3_600_000_000, "2005-01-01"),
        ("hours since 2005-01-01 00:00:00Z", 3_600_000_000, "2005-01-01"),
        ("hours since 2005-01-01 02:00:00 +02:00", 3_600_000_000, "2005-01-01"),
        ("hours since 2005-01-01 00:00:00 -0130", 3_600_000_000, "2005-01-01T01:30"),
        ("hours since 2005-01-01 00:00 +1", 3_600_000_000, "2004-12-31T23:00"),
    ],
)
def test_units_of_time(units: str, length: int, reference: str) -> None:
    assert parse_time_units(units) == (length, np.datetime64(reference, "us"))


@pytest.mark.parametrize(
    "units",
    [
        "m",
        "hours",
        "months since 2005-01-01",
        "years since 2005-01-01",
        "parsecs since 2005-01-01",
        "hours since yesterday",
        "hours since 2005-13-01",
        "hours since 2005-02-30",
        "hours since",
        "",
        None,
        7,
    ],
)
def test_what_are_no_units_of_time(units: Any) -> None:
    assert parse_time_units(units) is None


def test_numbers_with_units_of_time_become_instants() -> None:
    found = decoded(
        [0, 1, 25], {"units": "hours since 2005-01-01 00:00:00", "calendar": "standard"}
    )
    assert found.type_name == "datetime"
    np.testing.assert_array_equal(
        found.values, instants("2005-01-01T00", "2005-01-01T01", "2005-01-02T01")
    )
    assert found.attributes == {}
    assert found.encoding == {
        "units": "hours since 2005-01-01 00:00:00",
        "calendar": "standard",
    }


def test_fractions_of_a_unit() -> None:
    found = decoded([0.5, 1.25], {"units": "days since 2005-01-01"})
    np.testing.assert_array_equal(found.values, instants("2005-01-01T12", "2005-01-02T06"))


def test_a_time_that_is_missing_is_no_time() -> None:
    found = decoded([0.0, np.nan], {"units": "hours since 2005-01-01"})
    assert found.values[0] == np.datetime64("2005-01-01", "us")
    assert np.isnat(found.values[1])
    found = decoded([0, -1], {"units": "hours since 2005-01-01", "_FillValue": -1})
    assert np.isnat(found.values[1])


@pytest.mark.parametrize("calendar", ["noleap", "365_day", "360_day", "julian", "all_leap", 7])
def test_another_calendar_is_left_alone(calendar: Any) -> None:
    attributes = {"units": "days since 2005-01-01", "calendar": calendar}
    found = decoded([0, 59, 60], attributes)
    assert found.type_name == "int64"
    assert found.values.tolist() == [0, 59, 60]
    assert found.attributes == attributes
    assert found.encoding == {}


def test_times_before_the_gregorian_calendar_need_the_proleptic_one() -> None:
    attributes = {"units": "days since 1500-01-01", "calendar": "standard"}
    assert decoded([0], attributes).type_name == "int64"
    attributes["calendar"] = "proleptic_gregorian"
    assert decoded([0], attributes).values[0] == np.datetime64("1500-01-01", "us")


def test_times_out_of_range_are_left_alone() -> None:
    found = decoded([10**18], {"units": "days since 2005-01-01"})
    assert found.type_name == "int64"
    assert found.encoding == {}


def test_units_that_are_no_time_are_an_attribute() -> None:
    found = decoded([1.0], {"units": "MW"})
    assert found.attributes == {"units": "MW"}
    assert found.type_name == "float64"


def test_text_is_never_a_time() -> None:
    found = decoded(np.array(["a"], dtype=object), {"units": "hours since 2005-01-01"}, "string")
    assert found.values.tolist() == ["a"]


@given(
    st.lists(st.integers(-(10**6), 10**6), max_size=20),
    st.sampled_from(["seconds", "minutes", "hours", "days"]),
    st.datetimes(min_value=dt.datetime(1600, 1, 1), max_value=dt.datetime(2400, 1, 1)),
)
def test_instants_are_the_reference_plus_the_numbers(
    values: list[int], unit: str, reference: dt.datetime
) -> None:
    text = reference.replace(microsecond=0).isoformat(sep=" ")
    attributes = {"units": f"{unit} since {text}", "calendar": "proleptic_gregorian"}
    found = decoded(np.array(values, dtype="i8"), attributes)
    step = {"seconds": "s", "minutes": "m", "hours": "h", "days": "D"}[unit]
    expected = np.datetime64(text, "us") + np.array(values, dtype=f"timedelta64[{step}]")
    np.testing.assert_array_equal(found.values, expected.astype("datetime64[us]"))


# -- missing values ---------------------------------------------------------------------------


def test_the_fill_value_masks() -> None:
    found = decoded([1, -999, 3], {"_FillValue": -999, "long_name": "x"})
    assert found.values.tolist() == [1, None, 3]
    assert found.attributes == {"long_name": "x"}
    assert found.encoding == {"_FillValue": -999}


def test_a_fill_value_that_is_not_a_number_masks_what_is_not_a_number() -> None:
    found = decoded([1.0, np.nan], {"_FillValue": np.nan})
    assert np.ma.getmaskarray(found.values).tolist() == [False, True]


def test_several_markers_of_missing_values() -> None:
    attributes = {"_FillValue": -1, "missing_value": np.array([-2, -3])}
    found = decoded([0, -1, -2, -3, 4], attributes)
    assert found.values.tolist() == [0, None, None, None, 4]


def test_missing_text() -> None:
    values = np.array(["<NA>", "b"], dtype=object)
    found = decoded(values, {"_FillValue": ["<NA>"]}, "string")
    assert found.values.tolist() == [None, "b"]


def test_nothing_is_masked_if_nothing_is_missing() -> None:
    found = decoded([1, 2], {"_FillValue": -999})
    assert not isinstance(found.values, np.ma.MaskedArray)
    assert found.encoding == {"_FillValue": -999}


def test_a_marker_of_another_kind_masks_nothing() -> None:
    assert decoded([1, 2], {"_FillValue": "none"}).values.tolist() == [1, 2]
    assert decoded([1, 2], {"_FillValue": np.nan}).values.tolist() == [1, 2]


# -- packed values, truth values, unsigned integers -------------------------------------------


def test_packed_values() -> None:
    attributes = {"scale_factor": 0.5, "add_offset": 10.0, "_FillValue": -1}
    found = decoded(np.array([0, 2, -1], dtype="i2"), attributes)
    assert found.type_name == "float64"
    assert found.values.tolist() == [10.0, 11.0, None]
    assert found.encoding == {"_FillValue": -1, "scale_factor": 0.5, "add_offset": 10.0}


def test_a_factor_alone_and_an_offset_alone() -> None:
    assert decoded([2], {"scale_factor": 3}).values.tolist() == [6.0]
    assert decoded([2], {"add_offset": 3}).values.tolist() == [5.0]


def test_a_factor_that_is_no_number_is_left_alone() -> None:
    found = decoded([2], {"scale_factor": "two"})
    assert found.values.tolist() == [2]
    assert found.attributes == {"scale_factor": "two"}


def test_truth_values() -> None:
    found = decoded(np.array([1, 0], dtype="i1"), {"dtype": "bool"})
    assert found.type_name == "bool"
    assert found.values.tolist() == [True, False]
    assert found.encoding == {"dtype": "bool"}


def test_a_type_that_is_not_truth_is_an_attribute() -> None:
    found = decoded(np.array([1, 0], dtype="i1"), {"dtype": "string"})
    assert found.type_name == "int8"
    assert found.attributes == {"dtype": "string"}


def test_unsigned_integers() -> None:
    attributes = {"_Unsigned": "true", "_FillValue": -1}
    found = decoded(np.array([-1, -2, 5], dtype="i1"), attributes)
    assert found.type_name == "uint8"
    assert found.values.tolist() == [None, 254, 5]
    assert found.encoding == {"_Unsigned": "true", "_FillValue": 255}


# -- characters -------------------------------------------------------------------------------


def characters(*texts: str, width: int) -> np.ndarray:
    return np.array([list(text.ljust(width, "\0")) for text in texts], dtype="S1")


def test_characters_are_joined_along_the_last_axis() -> None:
    values = characters("ab", "hello", "", width=5)
    found = decode_values(values, {}, ("x", "length"), "char")
    assert found.type_name == "string"
    assert found.values.tolist() == ["ab", "hello", ""]
    assert found.dimensions == ("x",)
    assert found.encoding == {"char_dimension": "length"}


def test_characters_of_one_axis_are_one_text() -> None:
    found = decode_values(np.array(list("name"), dtype="S1"), {}, ("length",), "char")
    assert found.values.shape == ()
    assert found.values.item() == "name"
    assert found.dimensions == ()


def test_characters_in_utf_8() -> None:
    raw = "größe".encode()
    values = np.frombuffer(raw, dtype="S1").reshape(1, len(raw))
    assert decode_values(values, {}, ("x", "length"), "char").values.tolist() == ["größe"]


def test_no_characters_are_no_text() -> None:
    values = np.empty((2, 0), dtype="S1")
    assert decode_values(values, {}, ("x", "length"), "char").values.tolist() == ["", ""]


def test_bytes_that_are_no_characters_are_left_alone() -> None:
    values = np.array([b"a", b"b"], dtype="S1")
    assert decode_values(values, {}, ("x",), "string").values.tolist() == [b"a", b"b"]


# -- options ----------------------------------------------------------------------------------


def test_nothing_is_interpreted_on_request() -> None:
    attributes = {"units": "hours since 2005-01-01", "_FillValue": 0, "scale_factor": 2.0}
    found = decode_values(np.array([0, 1]), attributes, ("t",), "int64", DecodeOptions.none())
    assert found.values.tolist() == [0, 1]
    assert found.type_name == "int64"
    assert found.attributes == attributes
    assert found.encoding == {}


def test_a_single_convention_can_be_switched_off() -> None:
    found = decoded([0, 1], {"units": "hours since 2005-01-01"}, times=False)
    assert found.values.tolist() == [0, 1]
    assert found.attributes == {"units": "hours since 2005-01-01"}


def test_the_attributes_of_the_caller_are_not_changed() -> None:
    attributes = {"units": "hours since 2005-01-01", "_FillValue": -1}
    decoded([0, -1], attributes)
    assert attributes == {"units": "hours since 2005-01-01", "_FillValue": -1}
