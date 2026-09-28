"""The functions of the package, apart from those that need an extractor."""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path

import pytest

import coati
from coati import DumpOptions, JsonOptions
from coati.errors import SourceError
from support import files
from support.compare import as_json


@pytest.fixture
def source(tmp_path: Path) -> Path:
    return files.calliope07(tmp_path / "model.nc")


# -- what the package offers ------------------------------------------------------------------


def test_everything_that_is_listed_exists() -> None:
    for name in coati.__all__:
        assert hasattr(coati, name), name
    assert sorted(coati.__all__) == sorted(set(coati.__all__))


def test_the_modules_of_the_same_names_are_not_hidden() -> None:
    import coati.dataset
    import coati.results

    assert coati.results.__name__ == "coati.results"
    assert coati.dataset.__name__ == "coati.dataset"
    assert callable(coati.results_document)
    assert callable(coati.dataset_document)


# -- messages ---------------------------------------------------------------------------------


def test_the_package_does_not_decide_where_messages_go() -> None:
    handlers = logging.getLogger("coati").handlers
    assert any(isinstance(handler, logging.NullHandler) for handler in handlers)


# -- the dataset ------------------------------------------------------------------------------


def test_dump_writes_what_dataset_document_returns(source: Path, tmp_path: Path) -> None:
    output = tmp_path / "dataset.json"
    assert coati.dump(source, output) is None
    assert json.loads(output.read_text(encoding="utf-8")) == as_json(coati.dataset_document(source))


def test_the_dataset_document_describes_its_source(source: Path) -> None:
    assert coati.dataset_document(source)["metadata"]["source"] == {
        "name": "model.nc",
        "format": "netcdf4",
        "size": source.stat().st_size,
    }


def test_the_file_is_closed_afterwards(source: Path, tmp_path: Path) -> None:
    coati.dump(source, tmp_path / "dataset.json")
    coati.dataset_document(source)
    coati.inspect(source)
    coati.detect(source)
    source.unlink()
    assert not source.exists()


def test_an_output_that_cannot_be_written(source: Path, tmp_path: Path) -> None:
    with pytest.raises(OSError, match="No such file or directory") as caught:
        coati.dump(source, tmp_path / "missing" / "dataset.json")
    assert caught.value.filename == str(tmp_path / "missing" / "dataset.json")


def test_dump_writes_to_a_stream(source: Path) -> None:
    stream = io.StringIO()
    coati.dump(source, stream, DumpOptions(data=False), JsonOptions(indent=None))
    document = json.loads(stream.getvalue())
    assert set(document["groups"]) == {"inputs", "attrs", "results"}
    assert "data" not in document["groups"]["results"]["variables"]["flow_cap"]


# -- looking at a file ------------------------------------------------------------------------


def test_detect(source: Path, tmp_path: Path) -> None:
    assert coati.detect(source).id == "calliope-v0-7-0"
    assert coati.detect(files.pypsa_hdf5(tmp_path / "network.h5")).id == "pypsa-v1-2-4"
    other = files.write_netcdf(tmp_path / "other.nc", {"attributes": {"title": "x"}})
    assert coati.detect(other) is None


def test_inspect(source: Path) -> None:
    summary = coati.inspect(source)
    assert summary["source"]["name"] == "model.nc"
    assert summary["framework"] == {
        "id": "calliope-v0-7-0",
        "name": "calliope",
        "title": "Calliope",
        "version": "0.7.0",
        "family": "calliope-v0-7",
        "supported": True,
    }
    assert [group["path"] for group in summary["groups"]] == ["/", "/inputs", "/attrs", "/results"]
    results = summary["groups"][3]
    assert results["dimensions"]["timesteps"] == 3
    assert {
        "name": "flow_cap",
        "dtype": "float64",
        "dimensions": ["nodes", "techs", "carriers"],
        "shape": [2, 4, 1],
    } in results["variables"]
    assert summary["groups"][2]["attributes"] == ["config", "runtime"]
    assert summary["warnings"] == []
    assert as_json(summary) == summary


def test_inspect_a_file_of_no_framework(tmp_path: Path) -> None:
    other = files.write_netcdf(tmp_path / "other.nc", {"attributes": {"title": "x"}})
    assert coati.inspect(other)["framework"] is None


# -- a directory as the source ----------------------------------------------------------------


@pytest.mark.parametrize("name", ["a.h5", "a.hdf5", "a.nc", "a.nc4", "a.cdf", "a.NC", "a.H5"])
def test_the_files_that_a_directory_is_searched_for(tmp_path: Path, name: str) -> None:
    (tmp_path / name).touch()
    assert coati.find_source(tmp_path) == tmp_path / name


def test_a_directory_with_one_file(tmp_path: Path) -> None:
    folder = tmp_path / "run" / "results" / "20260928-1"
    folder.mkdir(parents=True)
    path = files.adopt_net0(folder / "optimization_results.h5")
    (folder / "solver_log.txt").write_text("log")
    (tmp_path / "run" / "input.json").write_text("{}")
    assert coati.find_source(tmp_path) == path
    assert coati.find_source(tmp_path / "run") == path
    assert coati.find_source(path) == path
    assert coati.detect(tmp_path / "run").name == "adopt-net0"
    assert coati.inspect(tmp_path)["source"]["name"] == path.name


def test_a_directory_with_several_files(tmp_path: Path) -> None:
    for position in range(10):
        folder = tmp_path / f"point{position}"
        folder.mkdir()
        (folder / "optimization_results.h5").touch()
    with pytest.raises(SourceError) as caught:
        coati.inspect(tmp_path)
    message = str(caught.value)
    assert message.startswith(f"{tmp_path}: the directory holds 10 data files; name one of them:")
    assert f"\n  {tmp_path / 'point0' / 'optimization_results.h5'}" in message
    assert f"{tmp_path / 'point8'}" not in message
    assert message.endswith("\n  ... and 2 more")


def test_a_directory_with_no_file(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("nothing")
    (tmp_path / "folder.nc").mkdir()
    with pytest.raises(SourceError, match="the directory holds no netCDF or HDF5 file"):
        coati.find_source(tmp_path)


def test_a_path_that_does_not_exist_is_returned_as_it_is(tmp_path: Path) -> None:
    assert coati.find_source(tmp_path / "missing.nc") == tmp_path / "missing.nc"
