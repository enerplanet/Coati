"""Writing JSON: what is written is JSON, and it says what the document says."""

from __future__ import annotations

import datetime as dt
import io
import json
import math
import os
import stat
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.extra import numpy as hnp

from coati.errors import EncodingError
from coati.jsonio import JsonOptions, dump, dumps, iterencode, write_file

COMPACT = JsonOptions(indent=None)


def strict(text: str) -> Any:
    """Parse JSON and refuse the constants that are not JSON."""

    def refuse(constant: str) -> None:
        raise AssertionError(f"{constant} is not JSON")

    return json.loads(text, parse_constant=refuse)


# -- scalars ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (None, "null"),
        (True, "true"),
        (False, "false"),
        (0, "0"),
        (-17, "-17"),
        (2**70, str(2**70)),
        (1.5, "1.5"),
        (0.1, "0.1"),
        (1e-7, "1e-07"),
        (1e22, "1e+22"),
        (-0.0, "-0.0"),
        ("text", '"text"'),
        ("", '""'),
        ('quote " and \\ backslash', r'"quote \" and \\ backslash"'),
        ("line\nbreak\ttab", r'"line\nbreak\ttab"'),
        ("\x00\x1f", r'"\u0000\u001f"'),
        ("größe 容量 🔋", '"größe 容量 🔋"'),
    ],
)
def test_scalars(value: Any, text: str) -> None:
    assert dumps(value) == text
    assert strict(text) == value


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (np.bool_(True), "true"),
        (np.int8(-3), "-3"),
        (np.uint64(2**64 - 1), str(2**64 - 1)),
        (np.int64(-(2**63)), str(-(2**63))),
        (np.float64(0.1), "0.1"),
        (np.float32(0.1), "0.1"),
        (np.float16(0.5), "0.5"),
        (np.str_("text"), '"text"'),
        (np.bytes_(b"text"), '"text"'),
        (b"caf\xc3\xa9", '"café"'),
        (np.datetime64("2030-01-01T12:30:00"), '"2030-01-01T12:30:00"'),
        (np.datetime64("2030-01-01"), '"2030-01-01"'),
        (np.datetime64("NaT", "us"), "null"),
        (dt.datetime(2030, 1, 1, 12, 30), '"2030-01-01T12:30:00"'),
        (dt.date(2030, 1, 1), '"2030-01-01"'),
        (np.ma.masked, "null"),
        (1 + 2j, "[1.0, 2.0]"),
        (np.complex128(1 - 2j), "[1.0, -2.0]"),
    ],
)
def test_scalars_of_numpy_and_of_time(value: Any, text: str) -> None:
    assert dumps(value) == text


def test_a_number_of_single_precision_is_written_as_it_reads() -> None:
    # As a double the number is 0.10000000149011612, which nobody has written.
    assert dumps(np.array([0.1, 0.2, 1e-5], dtype=np.float32)) == "[0.1, 0.2, 1e-05]"


def test_characters_outside_ascii_can_be_escaped() -> None:
    text = dumps("größe 容量", JsonOptions(ensure_ascii=True))
    assert text.isascii()
    assert text == json.dumps("größe 容量", ensure_ascii=True)
    assert strict(text) == "größe 容量"


def test_bytes_that_are_no_text_are_replaced_not_refused() -> None:
    assert dumps(b"\xff\xfe") == '"��"'


# -- numbers that are not finite --------------------------------------------------------------


NOT_FINITE = [float("nan"), float("inf"), float("-inf")]


@pytest.mark.parametrize("value", NOT_FINITE)
def test_not_finite_becomes_null_by_default(value: float) -> None:
    assert dumps(value) == "null"
    assert dumps([1.0, value]) == "[1.0, null]"
    assert dumps(np.array([1.0, value])) == "[1.0, null]"
    assert dumps(np.float32(value)) == "null"


@pytest.mark.parametrize(
    ("value", "name"),
    [(float("nan"), "NaN"), (float("inf"), "Infinity"), (float("-inf"), "-Infinity")],
)
def test_not_finite_can_be_written_as_text(value: float, name: str) -> None:
    options = JsonOptions(non_finite="string")
    assert dumps(value, options) == f'"{name}"'
    assert dumps([1.0, value], options) == f'[1.0, "{name}"]'
    assert dumps(np.array([1.0, value]), options) == f'[1.0, "{name}"]'


@pytest.mark.parametrize("value", NOT_FINITE)
def test_not_finite_can_be_refused(value: float) -> None:
    options = JsonOptions(non_finite="error")
    with pytest.raises(EncodingError, match=r"^\$: .* is not a JSON number"):
        dumps(value, options)
    with pytest.raises(EncodingError, match=r"^\$\.a\[1\]: "):
        dumps({"a": [1.0, value]}, options)
    with pytest.raises(EncodingError, match=r"^\$\.a\[1\]\[0\]: "):
        dumps({"a": np.array([[1.0, 2.0], [value, 1.0]])}, options)


def test_the_position_of_an_error_quotes_a_key_that_is_no_name() -> None:
    with pytest.raises(EncodingError, match=r'^\$\["a b"\]\.c\[0\]: NaN'):
        dumps({"a b": {"c": [float("nan")]}}, JsonOptions(non_finite="error"))


def test_what_is_masked_is_no_error() -> None:
    masked = np.ma.MaskedArray([1.0, np.nan, 3.0], mask=[False, True, False])
    assert dumps(masked, JsonOptions(non_finite="error")) == "[1.0, null, 3.0]"
    assert dumps(masked, JsonOptions(non_finite="string")) == "[1.0, null, 3.0]"


# -- rounding ---------------------------------------------------------------------------------


def test_numbers_are_written_in_full_by_default() -> None:
    assert dumps([1 / 3, np.float64(2 / 3)]) == "[0.3333333333333333, 0.6666666666666666]"


def test_rounding() -> None:
    options = JsonOptions(decimals=3)
    assert dumps(1 / 3, options) == "0.333"
    assert dumps([1 / 3, 2], options) == "[0.333, 2]"
    assert dumps(np.array([1 / 3, 2 / 3]), options) == "[0.333, 0.667]"
    assert dumps(np.float32(1 / 3), options) == "0.333"
    assert dumps({"a": (0.12345, "0.12345")}, options) == '{\n  "a": [0.123, "0.12345"]\n}'


def test_rounding_to_whole_numbers_keeps_the_type() -> None:
    assert dumps([1.5, 2.5, 7], JsonOptions(decimals=0)) == "[2.0, 2.0, 7]"


def test_rounding_keeps_a_number_that_has_no_digits_to_round() -> None:
    large = 7.017264410084998e16
    assert dumps(large, JsonOptions(decimals=4)) == "7.017264410084998e+16"
    assert dumps(np.array([large, 1e300]), JsonOptions(decimals=4)) == (
        "[7.017264410084998e+16, 1e+300]"
    )


def test_rounding_turns_negative_zero_into_zero() -> None:
    assert dumps([-0.0, -0.0001], JsonOptions(decimals=2)) == "[0.0, 0.0]"
    assert dumps(np.array([-0.0, -0.0001]), JsonOptions(decimals=2)) == "[0.0, 0.0]"
    assert dumps(np.array([-0.0])) == "[-0.0]"


# -- arrays -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("array", "text"),
    [
        (np.array([1, 2, 3], dtype=np.int16), "[1, 2, 3]"),
        (np.array([True, False]), "[true, false]"),
        (np.array(["a", "b"]), '["a", "b"]'),
        (np.array([b"a", b"bc"]), '["a", "bc"]'),
        (np.array(["a", None, 1.5], dtype=object), '["a", null, 1.5]'),
        (np.array([], dtype=float), "[]"),
        (np.zeros((0, 3)), "[]"),
        (np.zeros((2, 0)), "[[], []]"),
        (np.array(5.5), "5.5"),
        (np.array("text"), '"text"'),
        (np.arange(6).reshape(2, 3), "[[0, 1, 2], [3, 4, 5]]"),
        (np.arange(8).reshape(2, 2, 2), "[[[0, 1], [2, 3]], [[4, 5], [6, 7]]]"),
        (np.array([1 + 2j, 3 - 4j]), "[[1.0, 2.0], [3.0, -4.0]]"),
        (np.ma.MaskedArray([1, 2, 3], mask=[False, True, False]), "[1, null, 3]"),
        (np.ma.MaskedArray(["a", "b"], mask=[True, False]), '[null, "b"]'),
        (np.ma.MaskedArray(7, mask=True), "null"),
        (
            np.array(["2030-01-01T00:00:00", "NaT"], dtype="datetime64[ns]"),
            '["2030-01-01T00:00:00", null]',
        ),
        (np.array(["2030-01-01"], dtype="datetime64[D]"), '["2030-01-01"]'),
        (
            np.array(["2030-01-01T00:00:00.250"], dtype="datetime64[ms]"),
            '["2030-01-01T00:00:00.250"]',
        ),
        (np.array([b"\x01\xff"], dtype="V2"), '["Af8="]'),
    ],
)
def test_arrays(array: np.ndarray, text: str) -> None:
    assert dumps(array, COMPACT) == text.replace(", ", ",")
    strict(dumps(array))


def test_records_are_objects() -> None:
    records = np.array(
        [(1, 2.5, b"ab"), (2, np.nan, b"")], dtype=[("i", "i4"), ("f", "f8"), ("s", "S2")]
    )
    assert strict(dumps(records)) == [
        {"i": 1, "f": 2.5, "s": "ab"},
        {"i": 2, "f": None, "s": ""},
    ]
    assert strict(dumps(records[0])) == {"i": 1, "f": 2.5, "s": "ab"}


def test_records_with_arrays_and_records_inside() -> None:
    inner = np.dtype([("x", "i2"), ("y", "i2")])
    records = np.zeros(1, dtype=[("values", "f4", (2,)), ("point", inner)])
    records[0] = ([0.5, 1.5], (3, 4))
    assert strict(dumps(records)) == [{"values": [0.5, 1.5], "point": {"x": 3, "y": 4}}]


def test_arrays_of_different_lengths() -> None:
    ragged = np.empty(2, dtype=object)
    ragged[0] = np.array([1, 2])
    ragged[1] = np.array([3.5])
    assert dumps(ragged, COMPACT) == "[[1,2],[3.5]]"


def test_a_long_array_is_written_in_pieces_that_fit_together() -> None:
    values = np.arange(200_001, dtype=float)
    values[[0, 70_000, 200_000]] = np.nan
    chunks = list(iterencode(values, COMPACT))
    assert len(chunks) > 3
    parsed = strict("".join(chunks))
    assert len(parsed) == values.size
    assert parsed[0] is None
    assert parsed[70_000] is None
    assert parsed[200_000] is None
    assert parsed[1:70_000] == values[1:70_000].tolist()


@pytest.mark.parametrize(
    "value", [np.array([1, 2], dtype="timedelta64[s]"), np.timedelta64(1, "s")]
)
def test_what_json_has_no_form_for_is_refused(value: Any) -> None:
    with pytest.raises(EncodingError, match="cannot be written as JSON"):
        dumps({"a": value})


def test_an_object_of_another_kind_is_refused_with_its_position() -> None:
    with pytest.raises(EncodingError, match=r"^\$\.a\[1\]: a value of type object cannot"):
        dumps({"a": [1, object()]})


def test_a_key_that_is_no_text_is_refused() -> None:
    with pytest.raises(EncodingError, match=r"^\$\.a: the key 1 of type int is not a string"):
        dumps({"a": {1: 2}})


# -- layout -----------------------------------------------------------------------------------


DOCUMENT = {
    "name": "model",
    "empty": {},
    "nothing": [],
    "series": np.array([1.0, 2.0]),
    "table": np.arange(4).reshape(2, 2),
    "nested": {"list": [1, "two", None], "objects": [{"a": 1}, {"b": [2, 3]}]},
    "mixed": [1, [2, 3], {"c": 4}],
}

INDENTED = """\
{
  "name": "model",
  "empty": {},
  "nothing": [],
  "series": [1.0, 2.0],
  "table": [
    [0, 1],
    [2, 3]
  ],
  "nested": {
    "list": [1, "two", null],
    "objects": [
      {
        "a": 1
      },
      {
        "b": [2, 3]
      }
    ]
  },
  "mixed": [
    1,
    [2, 3],
    {
      "c": 4
    }
  ]
}"""


def test_a_series_stays_on_one_line_in_an_indented_document() -> None:
    assert dumps(DOCUMENT) == INDENTED


def test_the_compact_layout_has_no_whitespace() -> None:
    text = dumps(DOCUMENT, COMPACT)
    assert text == (
        '{"name":"model","empty":{},"nothing":[],"series":[1.0,2.0],"table":[[0,1],[2,3]],'
        '"nested":{"list":[1,"two",null],"objects":[{"a":1},{"b":[2,3]}]},'
        '"mixed":[1,[2,3],{"c":4}]}'
    )
    assert strict(text) == strict(INDENTED)


def test_the_width_of_the_indentation() -> None:
    assert (
        dumps({"a": {"b": 1}}, JsonOptions(indent=4)) == '{\n    "a": {\n        "b": 1\n    }\n}'
    )
    assert dumps({"a": {"b": 1}}, JsonOptions(indent=0)) == '{\n"a": {\n"b": 1\n}\n}'


def test_keys_keep_their_order_unless_sorted() -> None:
    document = {"b": 1, "a": {"d": 2, "c": 3}}
    assert list(strict(dumps(document))) == ["b", "a"]
    assert dumps(document, JsonOptions(indent=None, sort_keys=True)) == '{"a":{"c":3,"d":2},"b":1}'


def test_tuples_are_arrays() -> None:
    assert dumps((1, (2, 3)), COMPACT) == "[1,[2,3]]"


# -- values made when they are written --------------------------------------------------------


class Late:
    """A value that is made when it is written."""

    def __init__(self, value: Any) -> None:
        self.value = value
        self.calls = 0

    def __coati_json__(self) -> Any:
        self.calls += 1
        return self.value


def test_a_late_value_is_asked_for_when_it_is_written() -> None:
    late = Late({"data": np.array([1, 2])})
    chunks = iterencode({"first": 1, "late": late}, COMPACT)
    assert next(chunks) == "{"
    assert late.calls == 0
    assert "".join(chunks) == '"first":1,"late":{"data":[1,2]}}'
    assert late.calls == 1


def test_a_late_value_may_return_a_late_value() -> None:
    assert dumps(Late(Late([1, 2])), COMPACT) == "[1,2]"


# -- options ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "options",
    [
        {"indent": -1},
        {"indent": True},
        {"decimals": -1},
        {"decimals": False},
        {"non_finite": "zero"},
    ],
)
def test_options_that_make_no_sense_are_refused(options: dict) -> None:
    with pytest.raises(ValueError, match="must be"):
        JsonOptions(**options)


# -- writing ----------------------------------------------------------------------------------


def test_a_stream_gets_the_text_and_a_newline() -> None:
    stream = io.StringIO()
    dump({"a": 1}, stream, COMPACT)
    assert stream.getvalue() == '{"a":1}\n'


def test_a_file_is_written_as_utf_8_with_a_newline(tmp_path: Path) -> None:
    target = tmp_path / "out.json"
    write_file({"name": "größe"}, target, COMPACT)
    assert target.read_bytes() == '{"name":"größe"}\n'.encode()
    assert [path.name for path in tmp_path.iterdir()] == ["out.json"]


def test_a_file_is_replaced(tmp_path: Path) -> None:
    target = tmp_path / "out.json"
    target.write_text("old and much longer than what replaces it")
    write_file([1], target, COMPACT)
    assert target.read_text() == "[1]\n"


def test_a_failure_leaves_the_file_as_it_was(tmp_path: Path) -> None:
    target = tmp_path / "out.json"
    target.write_text("old")
    with pytest.raises(EncodingError):
        write_file({"a": [1, object()]}, target)
    assert target.read_text() == "old"
    assert [path.name for path in tmp_path.iterdir()] == ["out.json"]


@pytest.mark.skipif(os.name != "posix", reason="permissions of POSIX")
def test_a_new_file_has_the_permissions_of_a_new_file(tmp_path: Path) -> None:
    target = tmp_path / "out.json"
    previous = os.umask(0o027)
    try:
        write_file([1], target)
    finally:
        os.umask(previous)
    assert stat.S_IMODE(target.stat().st_mode) == 0o640


@pytest.mark.skipif(os.name != "posix", reason="permissions of POSIX")
def test_a_replaced_file_keeps_its_permissions(tmp_path: Path) -> None:
    target = tmp_path / "out.json"
    target.write_text("old")
    target.chmod(0o600)
    write_file([1], target)
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_a_directory_that_does_not_exist_is_named_in_the_error(tmp_path: Path) -> None:
    target = tmp_path / "missing" / "out.json"
    with pytest.raises(FileNotFoundError) as caught:
        write_file([1], target)
    assert caught.value.filename == str(target)


# -- properties -------------------------------------------------------------------------------

scalars = (
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text()
)
documents = st.recursive(
    scalars,
    lambda children: st.lists(children) | st.dictionaries(st.text(), children),
    max_leaves=30,
)


@given(documents, st.sampled_from([None, 0, 2]), st.booleans())
def test_what_is_written_reads_back_as_the_document(
    document: Any, indent: int | None, ensure_ascii: bool
) -> None:
    text = dumps(document, JsonOptions(indent=indent, ensure_ascii=ensure_ascii))
    assert strict(text) == document
    assert strict(text) == json.loads(json.dumps(document))


@given(documents)
def test_the_layouts_say_the_same(document: Any) -> None:
    assert strict(dumps(document)) == strict(dumps(document, COMPACT))


@given(
    hnp.arrays(
        dtype=st.sampled_from([np.float64, np.float32, np.int64, np.int8, np.uint16, np.bool_]),
        shape=hnp.array_shapes(min_dims=0, max_dims=3, min_side=0, max_side=4),
    ),
    st.sampled_from(["null", "string"]),
)
@settings(max_examples=200)
def test_an_array_reads_back_as_its_elements(array: np.ndarray, policy: str) -> None:
    parsed = strict(dumps(array, JsonOptions(indent=None, non_finite=policy)))

    def expected(value: Any) -> Any:
        if isinstance(value, list):
            return [expected(item) for item in value]
        if isinstance(value, float) and not math.isfinite(value):
            if policy == "null":
                return None
            return "NaN" if math.isnan(value) else "Infinity" if value > 0 else "-Infinity"
        return value

    if array.dtype == np.float32:
        array = array.astype(str).astype(np.float64)
    assert parsed == expected(array.tolist())


@given(st.floats(allow_nan=False, allow_infinity=False), st.integers(0, 12))
def test_rounding_is_the_same_for_a_number_and_for_an_array(value: float, decimals: int) -> None:
    text = dumps(value, JsonOptions(decimals=decimals))
    assert dumps(np.array([value]), JsonOptions(indent=None, decimals=decimals)) == f"[{text}]"
    assert math.isclose(float(text), value, rel_tol=1e-15, abs_tol=0.5 * 10.0**-decimals)
    assert text != "-0.0"
