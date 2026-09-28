"""The functions of the package that make the results of a model."""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path

import pytest

import coati
from coati import ExtractOptions, JsonOptions
from coati.errors import FrameworkError, SourceError
from support import files
from support.compare import as_json


@pytest.fixture
def source(tmp_path: Path) -> Path:
    return files.calliope07(tmp_path / "model.nc")


def test_convert_writes_the_document_and_returns_it(source: Path, tmp_path: Path) -> None:
    output = tmp_path / "out" / "results.json"
    output.parent.mkdir()
    document = coati.convert(source, output, "calliope-v0-7-0")
    assert json.loads(output.read_text(encoding="utf-8")) == as_json(document)
    assert output.read_text(encoding="utf-8").endswith("}\n")
    assert document["objective"] == 128.0


def test_convert_accepts_paths_as_text(source: Path, tmp_path: Path) -> None:
    output = tmp_path / "results.json"
    coati.convert(str(source), str(output))
    assert json.loads(output.read_text())["framework"] == "calliope"


def test_convert_writes_to_a_stream(source: Path) -> None:
    stream = io.StringIO()
    coati.convert(source, stream, json_options=JsonOptions(indent=None))
    text = stream.getvalue()
    assert text.endswith("}\n")
    assert "\n" not in text[:-1]
    assert json.loads(text)["objective"] == 128.0


def test_the_choices_reach_the_document(source: Path, tmp_path: Path) -> None:
    output = tmp_path / "results.json"
    coati.convert(
        source,
        output,
        options=ExtractOptions(labels=False),
        json_options=JsonOptions(decimals=0, sort_keys=True, indent=None),
    )
    document = json.loads(output.read_text())
    assert list(document)[:3] == ["capacities", "coordinates", "costs_by_location"]
    assert document["tech_metadata"]["pv"] == {"carrier_out": "power", "parent": "supply"}
    assert document["unmet_demand_timeseries"] == [0.0, 0.0, 0.0]


def test_results_document(source: Path) -> None:
    document = coati.results_document(source)
    assert document["dispatch"]["pv"].tolist() == [6.0, 8.0, 4.0]
    assert document["metadata"]["source"] == {
        "name": "model.nc",
        "format": "netcdf4",
        "size": source.stat().st_size,
    }


def test_read_results(source: Path) -> None:
    found = coati.read_results(source, "calliope")
    assert isinstance(found, coati.Results)
    assert found.framework.id == "calliope-v0-7-0"
    assert found.capacities["a::pv"] == 10.0
    assert isinstance(found.transmission_flow["a::b"], coati.Transmission)


def test_a_failure_leaves_the_output_as_it_was(source: Path, tmp_path: Path) -> None:
    output = tmp_path / "results.json"
    output.write_text("kept")
    with pytest.raises(FrameworkError):
        coati.convert(source, output, "pypsa-v1-2-4")
    with pytest.raises(SourceError):
        coati.convert(tmp_path / "missing.nc", output)
    assert output.read_text() == "kept"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["model.nc", "results.json"]


def test_an_output_that_cannot_be_written(source: Path, tmp_path: Path) -> None:
    with pytest.raises(OSError, match="No such file or directory") as caught:
        coati.convert(source, tmp_path / "missing" / "results.json")
    assert caught.value.filename == str(tmp_path / "missing" / "results.json")


def test_warnings_are_logged(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    path = files.calliope07(tmp_path / "model.nc", spores=2)
    with caplog.at_level(logging.WARNING, logger="coati"):
        document = coati.results_document(path, "calliope-v0-7-0-dev7")
    messages = [record.getMessage() for record in caplog.records]
    assert messages == [f"{path}: {warning}" for warning in document["warnings"]]
    assert len(messages) == 2
    assert "although Calliope 0.7.0.dev7 was named" in messages[0]
    assert "2 solutions of the SPORES mode" in messages[1]
    assert {record.name for record in caplog.records} == {"coati"}


def test_the_warnings_of_the_reader_are_part_of_the_document(tmp_path: Path) -> None:
    import h5py

    path = files.adopt_net0(tmp_path / "results.h5")
    with h5py.File(path, "a") as file:
        file["elsewhere"] = h5py.ExternalLink("other.h5", "/x")
    assert coati.results_document(path)["warnings"] == [
        "/elsewhere is a link into the file 'other.h5'; it is not followed"
    ]


def test_the_file_is_closed_afterwards(source: Path, tmp_path: Path) -> None:
    coati.convert(source, tmp_path / "results.json")
    coati.results_document(source)
    coati.read_results(source)
    source.unlink()
    assert not source.exists()


def test_a_directory_with_one_file(tmp_path: Path) -> None:
    folder = tmp_path / "run" / "results" / "20260928-1"
    folder.mkdir(parents=True)
    path = files.adopt_net0(folder / "optimization_results.h5")
    (folder / "solver_log.txt").write_text("log")
    document = coati.results_document(tmp_path, "adopt-net0-v0-1-10")
    assert document["metadata"]["source"]["name"] == path.name
    assert document["framework_version"] == "0.1.10"


def test_a_directory_with_several_files(tmp_path: Path) -> None:
    for position in range(10):
        folder = tmp_path / f"point{position}"
        folder.mkdir()
        (folder / "optimization_results.h5").touch()
    with pytest.raises(SourceError) as caught:
        coati.results_document(tmp_path)
    message = str(caught.value)
    assert message.startswith(f"{tmp_path}: the directory holds 10 data files; name one of them:")
    assert f"\n  {tmp_path / 'point0' / 'optimization_results.h5'}" in message
    assert f"{tmp_path / 'point8'}" not in message
    assert message.endswith("\n  ... and 2 more")
