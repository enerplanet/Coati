"""The dataset document: everything a file holds."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import pytest

import coati
from coati.dataset import DumpOptions, build_document
from coati.errors import CoatiError
from coati.readers import open_dataset
from support import files
from support.compare import as_json

NAN = float("nan")
TIME = {"units": files.TIME_UNITS, "calendar": files.CALENDAR}
PACKED = {"_FillValue": np.int16(-1), "scale_factor": 0.5, "long_name": "Packed"}


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return files.write_netcdf(
        tmp_path / "data.nc",
        {
            "attributes": {
                "title": "A file",
                "numbers": np.array([1.5, 2.5]),
                "meta": '{"author": "someone", "tags": ["a", "b"]}',
                "config": "init:\n  name: A model\n  weights: [1, 2]\nsolver: cbc\n",
                "broken": '{"not": json',
            },
            "dimensions": {"time": 3, "x": 2},
            "variables": {
                "time": (("time",), [0, 1, 2], TIME),
                "x": (("x",), ["a", "b"]),
                "values": (("time", "x"), [[1.0, NAN], [3.0, 4.0], [5.0, 6.0]], {"units": "MW"}),
                "packed": (("x",), np.array([2, -1], dtype="i2"), PACKED),
                "flags": (("x",), np.array([True, False])),
                "scalar": ((), 7),
            },
            "groups": {
                "inner": {
                    "attributes": {"note": "nested"},
                    "dimensions": {"y": 1},
                    "variables": {"matrix": (("y", "x"), [[1, 2]])},
                }
            },
        },
    )  # fmt: skip


def dataset_document(path: Path, **options: Any) -> dict:
    with open_dataset(path) as dataset:
        return as_json(build_document(dataset, DumpOptions(**options), lazy=False))


def test_the_document(path: Path) -> None:
    document = dataset_document(path)
    assert list(document) == [
        "schema_version",
        "format",
        "attributes",
        "dimensions",
        "variables",
        "groups",
        "warnings",
        "metadata",
    ]
    assert document["schema_version"] == "1.0"
    assert document["format"] == "netcdf4"
    assert document["warnings"] == []
    assert document["attributes"]["title"] == "A file"
    assert document["attributes"]["numbers"] == [1.5, 2.5]
    assert document["dimensions"] == {
        "time": {"size": 3, "unlimited": False},
        "x": {"size": 2, "unlimited": False},
    }
    assert list(document["variables"]) == ["time", "x", "values", "packed", "flags", "scalar"]


def test_metadata(path: Path) -> None:
    metadata = dataset_document(path)["metadata"]
    assert metadata["generator"] == "coati"
    assert metadata["generator_version"] == coati.__version__
    assert metadata["source"] == {"name": "data.nc", "format": "netcdf4"}
    assert set(metadata["properties"]) == {"_NCProperties"}


def test_the_path_of_the_file_is_not_part_of_the_document(path: Path) -> None:
    assert str(path.parent) not in json.dumps(dataset_document(path))


def test_variables_are_interpreted(path: Path) -> None:
    variables = dataset_document(path)["variables"]
    assert variables["time"] == {
        "dtype": "datetime",
        "dimensions": ["time"],
        "shape": [3],
        "attributes": {},
        "encoding": {"units": files.TIME_UNITS, "calendar": files.CALENDAR},
        "data": files.TIMESTAMPS,
    }
    assert variables["values"] == {
        "dtype": "float64",
        "dimensions": ["time", "x"],
        "shape": [3, 2],
        "attributes": {"units": "MW"},
        "encoding": {"_FillValue": None},
        "data": [[1.0, None], [3.0, 4.0], [5.0, 6.0]],
    }
    assert variables["packed"] == {
        "dtype": "float64",
        "dimensions": ["x"],
        "shape": [2],
        "attributes": {"long_name": "Packed"},
        "encoding": {"_FillValue": -1, "scale_factor": 0.5},
        "data": [1.0, None],
    }
    assert variables["flags"]["dtype"] == "bool"
    assert variables["flags"]["data"] == [True, False]
    assert variables["x"] == {
        "dtype": "string",
        "dimensions": ["x"],
        "shape": [2],
        "attributes": {},
        "data": ["a", "b"],
    }
    assert variables["scalar"]["shape"] == []
    assert variables["scalar"]["data"] == 7


def test_variables_as_they_are_stored(path: Path) -> None:
    variables = dataset_document(path, decode=False)["variables"]
    assert variables["time"] == {
        "dtype": "int64",
        "dimensions": ["time"],
        "shape": [3],
        "attributes": {"units": files.TIME_UNITS, "calendar": files.CALENDAR},
        "data": [0, 1, 2],
    }
    assert variables["packed"]["dtype"] == "int16"
    assert variables["packed"]["data"] == [2, -1]
    assert variables["packed"]["attributes"] == {
        "_FillValue": -1,
        "scale_factor": 0.5,
        "long_name": "Packed",
    }
    assert variables["flags"]["dtype"] == "int8"
    assert variables["flags"]["data"] == [1, 0]
    assert variables["flags"]["attributes"] == {"dtype": "bool"}
    assert variables["values"]["data"] == [[1.0, None], [3.0, 4.0], [5.0, 6.0]]


def test_groups(path: Path) -> None:
    assert dataset_document(path)["groups"] == {
        "inner": {
            "attributes": {"note": "nested"},
            "dimensions": {"y": {"size": 1, "unlimited": False}},
            "variables": {
                "matrix": {
                    "dtype": "int64",
                    "dimensions": ["y", "x"],
                    "shape": [1, 2],
                    "attributes": {},
                    "data": [[1, 2]],
                }
            },
            "groups": {},
        }
    }


def test_the_structure_alone(path: Path) -> None:
    document = dataset_document(path, data=False)
    assert document["variables"]["time"] == {
        "dtype": "datetime",
        "dimensions": ["time"],
        "shape": [3],
        "attributes": {},
        "encoding": {"units": files.TIME_UNITS, "calendar": files.CALENDAR},
    }
    assert '"data":' not in json.dumps(document)
    assert '"data_omitted"' not in json.dumps(document)


def test_large_variables_without_their_values(path: Path) -> None:
    variables = dataset_document(path, max_elements=3)["variables"]
    assert variables["values"] == {
        "dtype": "float64",
        "dimensions": ["time", "x"],
        "shape": [3, 2],
        "attributes": {"units": "MW"},
        "encoding": {"_FillValue": None},
        "data_omitted": True,
    }
    assert variables["time"]["data"] == files.TIMESTAMPS
    assert "data_omitted" not in variables["time"]
    assert all(
        "data" not in entry
        for entry in dataset_document(path, max_elements=0)["variables"].values()
    )


@pytest.mark.parametrize(
    ("patterns", "root", "inner"),
    [
        (("values",), ["values"], []),
        (("/values",), ["values"], []),
        (("matrix",), [], ["matrix"]),
        (("/inner/*",), [], ["matrix"]),
        (("/inner/matrix", "time"), ["time"], ["matrix"]),
        (("*a*",), ["values", "packed", "flags", "scalar"], ["matrix"]),
        (("/*",), ["time", "x", "values", "packed", "flags", "scalar"], ["matrix"]),
        (("[tx]*",), ["time", "x"], []),
        (("VALUES",), [], []),
        (("nothing",), [], []),
    ],
)
def test_choosing_variables(
    path: Path, patterns: tuple[str, ...], root: list[str], inner: list[str]
) -> None:
    document = dataset_document(path, variables=patterns)
    assert list(document["variables"]) == root
    assert list(document["groups"]["inner"]["variables"]) == inner
    assert document["dimensions"]["time"]["size"] == 3


def test_text_that_holds_a_document(path: Path) -> None:
    attributes = dataset_document(path, decode_text=True)["attributes"]
    assert attributes["meta"] == {"author": "someone", "tags": ["a", "b"]}
    assert attributes["config"] == {
        "init": {"name": "A model", "weights": [1, 2]},
        "solver": "cbc",
    }
    assert attributes["title"] == "A file"
    assert attributes["broken"] == '{"not": json'
    assert attributes["numbers"] == [1.5, 2.5]


def test_text_is_text_unless_asked_otherwise(path: Path) -> None:
    attributes = dataset_document(path)["attributes"]
    assert attributes["meta"] == '{"author": "someone", "tags": ["a", "b"]}'
    assert attributes["config"].startswith("init:\n")


def test_what_a_parser_of_yaml_returns_is_put_in_terms_of_json(tmp_path: Path) -> None:
    text = "when: 2030-01-01 12:00:00\nday: 2030-01-01\nset: !!set {a, b}\n1: one\nnan: .nan\n"
    path = files.write_netcdf(tmp_path / "data.nc", {"attributes": {"config": text}})
    assert dataset_document(path, decode_text=True)["attributes"]["config"] == {
        "when": "2030-01-01T12:00:00",
        "day": "2030-01-01",
        "set": ["a", "b"],
        "1": "one",
        "nan": None,
    }


@pytest.mark.parametrize(
    "text",
    ["one line: only", "two lines\nwithout a colon", "key: [unclosed\nother: 1", "- a\n- b: 1\n"],
)
def test_text_that_holds_no_mapping_stays_text(tmp_path: Path, text: str) -> None:
    path = files.write_netcdf(tmp_path / "data.nc", {"attributes": {"note": text}})
    document = dataset_document(path, decode_text=True)
    assert document["attributes"]["note"] in (text, ["a", {"b": 1}])


def test_yaml_needs_a_parser(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    original = builtins.__import__

    def without_yaml(name: str, *arguments: Any, **keywords: Any) -> Any:
        if name == "yaml":
            raise ImportError("No module named 'yaml'")
        return original(name, *arguments, **keywords)

    monkeypatch.setattr(builtins, "__import__", without_yaml)
    with pytest.raises(
        CoatiError, match=r"reading YAML needs PyYAML; install it with: pip install"
    ):
        dataset_document(path, decode_text=True)


def test_a_limit_below_zero_is_refused() -> None:
    with pytest.raises(ValueError, match="max_elements must not be negative"):
        DumpOptions(max_elements=-1)


def test_the_values_are_read_when_they_are_written(path: Path) -> None:
    with open_dataset(path) as dataset:
        document = build_document(dataset)
        entry = document["variables"]["values"]
        assert not isinstance(entry, dict)
        assert repr(entry) == "<entry of /values>"
        assert as_json(entry)["data"] == [[1.0, None], [3.0, 4.0], [5.0, 6.0]]
        eager = build_document(dataset, lazy=False)
        assert isinstance(eager["variables"]["values"], dict)
        assert as_json(eager) == as_json(document)


def test_a_plain_hdf5_file(tmp_path: Path) -> None:
    path = tmp_path / "data.h5"
    records = np.array([(1, 2.5, b"ab")], dtype=[("i", "i4"), ("f", "f8"), ("s", "S2")])
    with h5py.File(path, "w") as file:
        file.create_dataset("group/values", data=[[1.0, 2.0]])
        file.create_dataset("records", data=records)
        file.create_dataset("empty", data=h5py.Empty("f8"))
        file["outside"] = h5py.ExternalLink("other.h5", "/x")
    document = dataset_document(path)
    assert document["format"] == "hdf5"
    assert document["dimensions"] == {}
    assert document["groups"]["group"]["variables"]["values"] == {
        "dtype": "float64",
        "dimensions": [None, None],
        "shape": [1, 2],
        "attributes": {},
        "data": [[1.0, 2.0]],
    }
    assert document["variables"]["records"]["dtype"] == "compound"
    assert document["variables"]["records"]["data"] == [{"i": 1, "f": 2.5, "s": "ab"}]
    assert document["variables"]["empty"]["data"] is None
    assert document["warnings"] == [
        "/outside is a link into the file 'other.h5'; it is not followed"
    ]


def test_an_enumeration(tmp_path: Path) -> None:
    import netCDF4

    path = tmp_path / "data.nc"
    with netCDF4.Dataset(path, "w") as dataset:
        kind = dataset.createEnumType("i1", "kind", {"off": 0, "on": 1})
        dataset.createDimension("x", 2)
        dataset.createVariable("state", kind, ("x",))[:] = [1, 0]
    entry = dataset_document(path)["variables"]["state"]
    assert entry["enumeration"] == {"off": 0, "on": 1}
    assert entry["data"] == [1, 0]


def test_characters_are_text(tmp_path: Path) -> None:
    import netCDF4

    path = tmp_path / "data.nc"
    with netCDF4.Dataset(path, "w", format="NETCDF3_CLASSIC") as dataset:
        dataset.createDimension("x", 2)
        dataset.createDimension("length", 3)
        names = dataset.createVariable("names", "S1", ("x", "length"))
        names._Encoding = "none"
        names[:] = np.array([list("ab\0"), list("cde")], dtype="S1")
    assert dataset_document(path)["variables"]["names"] == {
        "dtype": "string",
        "dimensions": ["x"],
        "shape": [2],
        "attributes": {"_Encoding": "none"},
        "encoding": {"char_dimension": "length"},
        "data": ["ab", "cde"],
    }
    assert dataset_document(path, data=False)["variables"]["names"]["shape"] == [2]
    raw = dataset_document(path, decode=False)["variables"]["names"]
    assert raw["dtype"] == "char"
    assert raw["shape"] == [2, 3]
    assert raw["data"] == [["a", "b", ""], ["c", "d", "e"]]
