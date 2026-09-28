"""Reading single values from the YAML that Calliope embeds in its files."""

from __future__ import annotations

from typing import Any

import pytest
import yaml
from hypothesis import given
from hypothesis import strategies as st

from coati.yamltext import exists, scalar

DOCUMENT = """\
# The configuration of a model.
init:
  name: National-scale example model
  calliope_version: 0.7.0
  subset:
    timesteps:
    - '2005-01-01'
    - '2005-01-02'
  resample: {}
  extra_math: []
  time_cluster:
  mode: base   # one of base, operate and spores
build:
  backend: pyomo
  ensure_feasibility: true
  operate:
    window: 24h
solve:
  solver: cbc
  solver_io:
  zero_threshold: 1e-10
  spores:
    number: 3
'quoted key': 'it''s quoted'
"double": "with: a colon"
folded:
  /a/path/that/is/too/long/for/one/line
quoted and folded: 'Automatically inserted: specifies that this node is a
  transmission-only node.'
plain and folded: a value that goes on
  on the next line
empty text: ''
termination_condition: optimal
"""


@pytest.mark.parametrize(
    ("keys", "value"),
    [
        (("termination_condition",), "optimal"),
        (("init", "name"), "National-scale example model"),
        (("init", "calliope_version"), "0.7.0"),
        (("init", "mode"), "base"),
        (("build", "backend"), "pyomo"),
        (("build", "ensure_feasibility"), "true"),
        (("build", "operate", "window"), "24h"),
        (("solve", "solver"), "cbc"),
        (("solve", "zero_threshold"), "1e-10"),
        (("solve", "spores", "number"), "3"),
        (("quoted key",), "it's quoted"),
        (("double",), "with: a colon"),
        (("folded",), "/a/path/that/is/too/long/for/one/line"),
        (
            ("quoted and folded",),
            "Automatically inserted: specifies that this node is a transmission-only node.",
        ),
        (("plain and folded",), "a value that goes on on the next line"),
        (("empty text",), ""),
    ],
)
def test_a_value_is_found_by_its_path(keys: tuple[str, ...], value: str) -> None:
    assert scalar(DOCUMENT, *keys) == value
    assert exists(DOCUMENT, *keys)


@pytest.mark.parametrize(
    "keys",
    [
        ("init",),
        ("init", "subset"),
        ("init", "subset", "timesteps"),
        ("init", "resample"),
        ("init", "extra_math"),
        ("init", "time_cluster"),
        ("solve", "solver_io"),
        ("solve", "spores"),
    ],
)
def test_what_is_no_single_value_is_none(keys: tuple[str, ...]) -> None:
    assert scalar(DOCUMENT, *keys) is None
    assert exists(DOCUMENT, *keys)


@pytest.mark.parametrize(
    "keys",
    [
        ("missing",),
        ("init", "missing"),
        ("name",),
        ("solver",),
        ("init", "solver"),
        ("init", "name", "deeper"),
        ("build", "window"),
        ("termination",),
        ("termination_condition_of_another",),
        ("'2005-01-01'",),
    ],
)
def test_a_path_that_does_not_exist(keys: tuple[str, ...]) -> None:
    assert scalar(DOCUMENT, *keys) is None
    assert not exists(DOCUMENT, *keys)


def test_a_key_is_found_at_its_own_level_only() -> None:
    document = "outer:\n  name: inner\nname: outer\n"
    assert scalar(document, "name") == "outer"
    assert scalar(document, "outer", "name") == "inner"
    document = "outer:\n  inner:\n    name: deep\n  other: 1\n"
    assert scalar(document, "outer", "name") is None


def test_a_list_at_the_level_of_its_key_ends_nothing() -> None:
    document = "first:\n- a\n- b\nsecond: value\n"
    assert scalar(document, "first") is None
    assert scalar(document, "second") == "value"


@pytest.mark.parametrize("text", ["null", "~", "Null", "NULL", ""])
def test_null(text: str) -> None:
    assert scalar(f"key: {text}\n", "key") is None
    assert exists(f"key: {text}\n", "key")


@pytest.mark.parametrize(
    "text", ["{a: 1}", "[1, 2]", "|", ">-", "&anchor value", "*alias", "!!str x"]
)
def test_what_this_module_does_not_read(text: str) -> None:
    assert scalar(f"key: {text}\n", "key") is None


@pytest.mark.parametrize("document", [None, 7, b"key: value", ["key: value"], ""])
def test_what_is_no_document(document: Any) -> None:
    assert scalar(document, "key") is None
    assert not exists(document, "key")


def test_no_path() -> None:
    assert scalar(DOCUMENT) is None
    assert not exists(DOCUMENT)


def test_an_unfinished_quotation() -> None:
    assert scalar("key: 'never closed\n", "key") is None
    assert scalar('key: "never closed\n', "key") is None


def test_markers_and_comments_are_skipped() -> None:
    document = "---\n# a comment\n\nkey: value\n\n  # indented comment\nother: 1\n"
    assert scalar(document, "key") == "value"
    assert scalar(document, "other") == "1"


# -- against a YAML parser --------------------------------------------------------------------

keys = st.text(st.characters(min_codepoint=97, max_codepoint=122), min_size=1, max_size=8)
values = (
    st.none()
    | st.booleans()
    | st.integers(-(10**6), 10**6)
    | st.floats(allow_nan=False, allow_infinity=False, width=32)
    | st.text(st.characters(min_codepoint=32, max_codepoint=126), max_size=120)
)
mappings = st.recursive(
    st.dictionaries(keys, values, max_size=4),
    lambda children: st.dictionaries(
        keys, values | children | st.lists(values, max_size=3), max_size=4
    ),
    max_leaves=12,
)


def leaves(node: Any, path: tuple[str, ...] = ()) -> Any:
    if isinstance(node, dict):
        for key, value in node.items():
            yield from leaves(value, (*path, key))
    else:
        yield path, node


@given(mappings, st.sampled_from([40, 80, 1000]))
def test_what_is_found_is_what_a_parser_finds(mapping: dict, width: int) -> None:
    document = yaml.safe_dump(mapping, default_flow_style=False, width=width)
    for path, expected in leaves(mapping):
        if not path:
            continue
        found = scalar(document, *path)
        assert exists(document, *path)
        if expected is None or isinstance(expected, (list, dict)):
            assert found is None
        elif isinstance(expected, str):
            assert found == expected
        else:
            assert found is not None
            assert yaml.safe_load(f"key: {found}") == {"key": expected}
