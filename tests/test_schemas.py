"""The JSON Schemas of the two documents."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from importlib import resources
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from jsonschema import Draft202012Validator

import coati
from coati import DumpOptions, ExtractOptions
from coati.dataset import SCHEMA_VERSION as DATASET_VERSION
from coati.results.document import SCHEMA_VERSION as RESULTS_VERSION
from support import files
from support.compare import as_json

Builder = Callable[[Path], Path]

MODELS: dict[str, Builder] = {
    "calliope-0.6": lambda folder: files.calliope06(folder / "model.nc"),
    "calliope-0.7": lambda folder: files.calliope07(folder / "model.nc"),
    "calliope-0.7-spores": lambda folder: files.calliope07(folder / "model.nc", spores=2),
    "calliope-0.7-operate": lambda folder: files.calliope07(folder / "model.nc", operate=True),
    "calliope-0.7-unsolved": lambda folder: files.calliope07(folder / "model.nc", solved=False),
    "pypsa-netcdf": lambda folder: files.pypsa_netcdf(folder / "network.nc"),
    "pypsa-unsolved": lambda folder: files.pypsa_netcdf(folder / "network.nc", solved=False),
    "pypsa-hdf5": lambda folder: files.pypsa_hdf5(folder / "network.h5"),
    "adopt-net0": lambda folder: files.adopt_net0(folder / "results.h5"),
    "adopt-net0-periods": lambda folder: files.adopt_net0(
        folder / "results.h5", periods=("early", "late"), typical_days=1, alike=True
    ),
}


def schema(name: str) -> dict[str, Any]:
    text = resources.files("coati.schemas").joinpath(f"{name}.schema.json").read_text("utf-8")
    return json.loads(text)


def errors(name: str, document: Any) -> list[str]:
    validator = Draft202012Validator(
        schema(name), format_checker=Draft202012Validator.FORMAT_CHECKER
    )
    return [
        f"{error.json_path}: {error.message}"
        for error in sorted(validator.iter_errors(document), key=lambda error: error.json_path)
    ]


@pytest.fixture(params=sorted(MODELS))
def source(request: pytest.FixtureRequest, tmp_path: Path) -> Path:
    return MODELS[request.param](tmp_path)


# -- the schemas themselves -------------------------------------------------------------------


@pytest.mark.parametrize("name", ["results", "dataset"])
def test_the_schemas_are_schemas(name: str) -> None:
    found = schema(name)
    Draft202012Validator.check_schema(found)
    assert found["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    version = found["properties"]["schema_version"]["const"]
    assert (
        found["$id"] == f"https://enerplanet.github.io/Coati/schemas/{name}-{version}.schema.json"
    )
    assert found["title"] == f"Coati {name} document"
    assert found["type"] == "object"


def test_the_versions_are_those_of_the_documents() -> None:
    assert schema("results")["properties"]["schema_version"]["const"] == RESULTS_VERSION
    assert schema("dataset")["properties"]["schema_version"]["const"] == DATASET_VERSION


@pytest.mark.parametrize("name", ["results", "dataset"])
def test_everything_is_described(name: str) -> None:
    def undescribed(node: dict[str, Any], path: str) -> list[str]:
        missing = []
        for key, entry in node.get("properties", {}).items():
            if "description" not in entry and "$ref" not in entry:
                missing.append(f"{path}.{key}")
            missing += undescribed(entry, f"{path}.{key}")
        for keyword in ("additionalProperties", "items"):
            if isinstance(node.get(keyword), dict):
                missing += undescribed(node[keyword], f"{path}.{keyword}")
        for key, entry in node.get("$defs", {}).items():
            missing += undescribed(entry, f"{path}.$defs.{key}")
        return missing

    found = schema(name)
    assert found["description"]
    assert undescribed(found, "$") == []


@pytest.mark.parametrize("name", ["results", "dataset"])
def test_every_reference_leads_somewhere(name: str) -> None:
    found = schema(name)

    def references(node: Any) -> list[str]:
        if isinstance(node, dict):
            own = [node["$ref"]] if "$ref" in node else []
            return own + [ref for entry in node.values() for ref in references(entry)]
        if isinstance(node, list):
            return [ref for entry in node for ref in references(entry)]
        return []

    used = set(references(found))
    assert used
    for reference in used:
        assert reference.startswith("#/$defs/"), reference
        assert reference.removeprefix("#/$defs/") in found["$defs"], reference
    assert {f"#/$defs/{name}" for name in found["$defs"]} == used


# -- the results document ---------------------------------------------------------------------


def test_the_results_are_valid(source: Path) -> None:
    document = as_json(coati.results_document(source))
    assert errors("results", document) == []


def test_the_results_are_valid_without_labels(source: Path) -> None:
    document = as_json(coati.results_document(source, options=ExtractOptions(labels=False)))
    assert errors("results", document) == []


def test_the_results_are_valid_with_numbers_as_text(source: Path) -> None:
    document = as_json(coati.results_document(source), non_finite="string")
    assert errors("results", document) == []


def test_the_results_are_valid_with_times_that_were_made(tmp_path: Path) -> None:
    options = ExtractOptions(time_start="2030-01-01", time_step="1h", period="late")
    path = files.adopt_net0(tmp_path / "results.h5", periods=("early", "late"))
    assert errors("results", as_json(coati.results_document(path, options=options))) == []


def test_every_key_of_the_results_is_described(source: Path) -> None:
    document = as_json(coati.results_document(source))
    assert set(document) <= set(schema("results")["properties"])
    assert set(schema("results")["required"]) <= set(document)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d.pop("capacities"), "'capacities' is a required property"),
        (lambda d: d.update(schema_version="2.0"), "'1.0' was expected"),
        (lambda d: d.update(success="yes"), "'yes' is not of type 'boolean'"),
        (lambda d: d.update(demand_timeseries={"a": [1.0]}), "is not of type 'array'"),
        (lambda d: d.update(framework="oemof"), "'oemof' is not one of"),
        (lambda d: d["capacities"].update({"a::pv": "much"}), "'much' is not"),
        (lambda d: d["dispatch"].update({"pv": [1.0, "x"]}), "'x' is not"),
        (lambda d: d["transmission_flow"]["a::b"].pop("to"), "'to' is a required property"),
        (lambda d: d["tech_metadata"]["pv"].pop("parent"), "'parent' is a required property"),
        (lambda d: d["metadata"].pop("generator_version"), "is a required property"),
        (lambda d: d.update(warnings="none"), "'none' is not of type 'array'"),
    ],
)
def test_what_is_wrong_is_found(tmp_path: Path, change: Callable, message: str) -> None:
    document = as_json(coati.results_document(files.calliope07(tmp_path / "model.nc")))
    assert errors("results", document) == []
    changed = copy.deepcopy(document)
    change(changed)
    found = errors("results", changed)
    assert any(message in error for error in found), found


def test_a_key_that_the_schema_does_not_know_is_refused(tmp_path: Path) -> None:
    document = as_json(coati.results_document(files.calliope07(tmp_path / "model.nc")))
    document["shadow_prices"] = {"a": [1.0]}
    assert errors("results", document) == [
        "$: Additional properties are not allowed ('shadow_prices' was unexpected)"
    ]


def test_the_details_may_hold_anything(tmp_path: Path) -> None:
    document = as_json(coati.results_document(files.calliope07(tmp_path / "model.nc")))
    document["details"] = {"anything": [1, "two", {"three": None}]}
    assert errors("results", document) == []


# -- the dataset document ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "options",
    [
        DumpOptions(),
        DumpOptions(data=False),
        DumpOptions(decode=False),
        DumpOptions(decode_text=True),
        DumpOptions(max_elements=2),
        DumpOptions(variables=("flow*", "generators*", "size")),
    ],
    ids=["default", "no-data", "raw", "text", "limit", "chosen"],
)
def test_the_dataset_is_valid(source: Path, options: DumpOptions) -> None:
    document = as_json(coati.dataset_document(source, options))
    assert errors("dataset", document) == []


def test_the_dataset_is_valid_with_numbers_as_text(source: Path) -> None:
    document = as_json(coati.dataset_document(source), non_finite="string")
    assert errors("dataset", document) == []


@pytest.mark.parametrize("name", ["classic", "64bit-offset", "64bit-data"])
def test_the_dataset_of_a_classic_file_is_valid(tmp_path: Path, name: str) -> None:
    content = {
        "dimensions": {"time": None, "x": 2, "letters": 3},
        "attributes": {"title": "classic", "numbers": [1.0, 2.0]},
        "variables": {
            "time": (("time",), np.array([0, 1, 2], dtype="i4"), {"units": files.TIME_UNITS}),
            "values": (("time", "x"), [[1.0, 2.0], [3.0, float("nan")], [5.0, 6.0]]),
            "names": (("x", "letters"), np.array([[b"a", b"b", b"c"], [b"d", b"e", b""]], "S1")),
            "scalar": ((), np.int16(4)),
        },
    }
    file_format = "NETCDF3_" + name.upper().replace("-", "_")
    path = files.write_netcdf(tmp_path / "data.nc", content, file_format)
    document = as_json(coati.dataset_document(path))
    assert errors("dataset", document) == []
    assert document["format"] == f"netcdf3-{name}"
    assert document["variables"]["names"]["data"] == ["abc", "de"]
    assert document["dimensions"]["time"] == {"size": 3, "unlimited": True}


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d.pop("format"), "'format' is a required property"),
        (lambda d: d.update(format="grib"), "'grib' is not one of"),
        (lambda d: d.update(schema_version="0"), "was expected"),
        (lambda d: d["dimensions"]["x"].update(size=-1), "-1 is less than the minimum of 0"),
        (lambda d: d["dimensions"]["x"].pop("unlimited"), "'unlimited' is a required property"),
        (lambda d: d["dimensions"].update(y=2), "2 is not of type 'object'"),
        (lambda d: d["variables"]["values"].update(unit="MW"), "'unit' was unexpected"),
        (lambda d: d["variables"]["values"].update(data_omitted=False), "True was expected"),
        (lambda d: d["variables"]["values"].pop("dtype"), "'dtype' is a required property"),
        (lambda d: d["variables"]["values"].update(shape=[2.5]), "2.5 is not of type 'integer'"),
        (lambda d: d["variables"]["values"].update(dimensions="x"), "'x' is not of type 'array'"),
    ],
)
def test_what_is_wrong_with_a_dataset_is_found(
    tmp_path: Path, change: Callable, message: str
) -> None:
    content = {"dimensions": {"x": 2}, "variables": {"values": (("x",), [1.0, 2.0])}}
    document = as_json(coati.dataset_document(files.write_netcdf(tmp_path / "data.nc", content)))
    assert errors("dataset", document) == []
    change(document)
    found = errors("dataset", document)
    assert any(message in error for error in found), found
