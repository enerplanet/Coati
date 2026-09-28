"""Choosing the reader by what a file holds, and the tables of pandas."""

from __future__ import annotations

import bz2
import gzip
import lzma
import os
import pickle
import zipfile
from pathlib import Path

import h5py
import netCDF4
import numpy as np
import pytest

from coati.errors import SourceError
from coati.model import Group
from coati.readers import open_dataset, pytables, sniff
from support import files

# -- choosing the reader ----------------------------------------------------------------------


def test_the_extension_does_not_matter(tmp_path: Path) -> None:
    classic = tmp_path / "classic.h5"
    netCDF4.Dataset(classic, "w", format="NETCDF3_CLASSIC").close()
    hdf5 = tmp_path / "hdf5.txt"
    h5py.File(hdf5, "w").close()
    assert sniff(classic) == "netcdf3"
    assert sniff(hdf5) == "hdf5"
    with open_dataset(classic) as dataset:
        assert dataset.format == "netcdf3-classic"
    with open_dataset(hdf5) as dataset:
        assert dataset.format == "hdf5"


def test_a_path_may_be_text(tmp_path: Path) -> None:
    path = files.calliope06(tmp_path / "model.nc")
    with open_dataset(str(path)) as dataset:
        assert dataset.source == path


def test_an_hdf5_file_behind_a_user_block(tmp_path: Path) -> None:
    path = tmp_path / "data.h5"
    with h5py.File(path, "w", userblock_size=512) as file:
        file.create_dataset("values", data=[1, 2])
    with path.open("r+b") as stream:
        stream.write(b"#!/bin/sh\n")
    assert sniff(path) == "hdf5"
    with open_dataset(path) as dataset:
        assert dataset.variables["values"].read().tolist() == [1, 2]


def test_a_file_that_does_not_exist(tmp_path: Path) -> None:
    with pytest.raises(SourceError, match=r"missing\.nc: no such file$"):
        open_dataset(tmp_path / "missing.nc")


def test_a_directory(tmp_path: Path) -> None:
    with pytest.raises(SourceError, match="is a directory, not a file"):
        open_dataset(tmp_path)


def test_an_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.nc"
    path.touch()
    with pytest.raises(SourceError, match=r"empty\.nc: the file is empty$"):
        open_dataset(path)


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="permissions of POSIX")
def test_a_file_that_may_not_be_read(tmp_path: Path) -> None:
    path = files.calliope06(tmp_path / "model.nc")
    path.chmod(0)
    try:
        with pytest.raises(SourceError, match=r"model\.nc: cannot be read: Permission denied"):
            open_dataset(path)
    finally:
        path.chmod(0o600)


def packed(tmp_path: Path, name: str) -> Path:
    source = files.calliope06(tmp_path / "model.nc").read_bytes()
    path = tmp_path / name
    if name.endswith(".gz"):
        path.write_bytes(gzip.compress(source))
    elif name.endswith(".xz"):
        path.write_bytes(lzma.compress(source))
    elif name.endswith(".bz2"):
        path.write_bytes(bz2.compress(source))
    else:
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("model.nc", source)
    return path


@pytest.mark.parametrize(
    ("name", "advice"),
    [
        ("model.nc.gz", "it is compressed with gzip; decompress it first"),
        ("model.nc.xz", "it is compressed with xz; decompress it first"),
        ("model.nc.bz2", "it is compressed with bzip2; decompress it first"),
        ("model.zip", "it is a ZIP archive; extract it first"),
    ],
)
def test_a_packed_file_is_recognised(tmp_path: Path, name: str, advice: str) -> None:
    with pytest.raises(SourceError) as caught:
        open_dataset(packed(tmp_path, name))
    assert str(caught.value).endswith(f"{name}: not a netCDF or HDF5 file; {advice}")


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b'{"capacities": {}}', "not a netCDF or HDF5 file; it looks like JSON"),
        (b"[1, 2, 3]", "not a netCDF or HDF5 file; it looks like JSON"),
        (b"name,bus\ngas,hub\n", "not a netCDF or HDF5 file"),
        (b"CDF\x07 and more", "not a netCDF or HDF5 file"),
        (b"CD", "not a netCDF or HDF5 file"),
    ],
)
def test_a_file_of_another_kind(tmp_path: Path, content: bytes, message: str) -> None:
    path = tmp_path / "data.nc"
    path.write_bytes(content)
    with pytest.raises(SourceError) as caught:
        open_dataset(path)
    assert str(caught.value) == f"{path}: {message}"


# -- the tables of pandas ---------------------------------------------------------------------


@pytest.fixture
def stored(tmp_path: Path) -> Path:
    path = tmp_path / "store.h5"
    with h5py.File(path, "w") as file:
        files.write_frame(
            file.create_group("table"),
            [0, 1, 2],
            {
                "name": ["a", "b", "nan"],
                "bus": ["x", "y", "z"],
                "size": [1.5, 2.5, np.nan],
                "count": [1, 2, 3],
                "flag": [True, False, True],
                "when": np.array(["2030-01-01", "2030-01-02", "NaT"], dtype="datetime64[us]"),
            },
        )
        files.write_frame(file.create_group("named"), ["first", "second"], {0: [1.0, 2.0]})
        file.create_group("other").create_dataset("table", data=[1, 2])
    return path


def test_a_table_is_recognised(stored: Path) -> None:
    with open_dataset(stored) as dataset:
        assert pytables.is_frame(dataset.groups["table"])
        assert pytables.is_frame(dataset.groups["named"])
        assert not pytables.is_frame(dataset.groups["other"])
        assert not pytables.is_frame(dataset)


def test_the_columns_of_a_table(stored: Path) -> None:
    with open_dataset(stored) as dataset:
        frame = pytables.read_frame(dataset.groups["table"])
    assert len(frame) == 3
    assert frame.index.tolist() == [0, 1, 2]
    assert set(frame.columns) == {"name", "bus", "size", "count", "flag", "when"}
    assert frame.column("bus").tolist() == ["x", "y", "z"]
    assert frame.column("count").tolist() == [1, 2, 3]
    assert frame.column("flag").tolist() == [True, False, True]
    assert frame.column("flag").dtype == bool
    assert frame.column("size")[:2].tolist() == [1.5, 2.5]
    assert np.isnan(frame.column("size")[2])
    assert frame.column("missing") is None


def test_missing_text_is_recognised_by_the_word_that_stands_for_it(stored: Path) -> None:
    with open_dataset(stored) as dataset:
        frame = pytables.read_frame(dataset.groups["table"])
    assert frame.column("name").tolist() == ["a", "b", None]


def test_times_have_the_resolution_that_the_table_states(stored: Path) -> None:
    with open_dataset(stored) as dataset:
        when = pytables.read_frame(dataset.groups["table"]).column("when")
    assert when.dtype == np.dtype("datetime64[us]")
    assert when[1] == np.datetime64("2030-01-02")
    assert np.isnat(when[2])


def test_times_of_an_older_pandas_are_nanoseconds(tmp_path: Path) -> None:
    path = tmp_path / "store.h5"
    with h5py.File(path, "w") as file:
        group = file.create_group("table")
        files.write_frame(group, [0], {"when": np.array(["2030-01-01"], dtype="datetime64[ns]")})
        group["table"].attrs["values_block_0_dtype"] = np.bytes_("datetime64")
    with open_dataset(path) as dataset:
        when = pytables.read_frame(dataset.groups["table"]).column("when")
    assert when[0] == np.datetime64("2030-01-01")


def test_a_table_with_names_as_its_index_and_numbers_as_its_columns(stored: Path) -> None:
    with open_dataset(stored) as dataset:
        frame = pytables.read_frame(dataset.groups["named"])
    assert frame.index.tolist() == ["first", "second"]
    assert frame.column(0).tolist() == [1.0, 2.0]


def test_what_is_no_table_is_refused(stored: Path) -> None:
    with (
        open_dataset(stored) as dataset,
        pytest.raises(SourceError, match="/other holds no table of pandas"),
    ):
        pytables.read_frame(dataset.groups["other"])


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("delete", "the names of the columns of values_block_0 are missing"),
        ("length", "the names of the columns of values_block_0 are damaged"),
        ("number", "the names of the columns of values_block_0 are damaged"),
    ],
)
def test_a_table_whose_columns_have_no_proper_names(
    tmp_path: Path, change: str, message: str
) -> None:
    path = tmp_path / "store.h5"
    with h5py.File(path, "w") as file:
        group = file.create_group("table")
        files.write_frame(group, [0], {"size": [1.0]})
        attributes = group["table"].attrs
        if change == "delete":
            del attributes["values_block_0_kind"]
        elif change == "length":
            attributes["values_block_0_kind"] = np.bytes_(pickle.dumps(["a", "b"], protocol=0))
        else:
            attributes["values_block_0_kind"] = np.bytes_(pickle.dumps(7, protocol=0))
    with open_dataset(path) as dataset, pytest.raises(SourceError, match=message):
        pytables.read_frame(dataset.groups["table"])


# -- pickles ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [["name", "bus"], [0, 1, 2], ("a", 1), {"a": [1, 2.5, None, True]}, "text", 7, [], None],
)
@pytest.mark.parametrize("protocol", [0, 2, 5])
def test_pickles_of_plain_values_are_loaded(value: object, protocol: int) -> None:
    assert pytables.unpickle(pickle.dumps(value, protocol=protocol)) == value


def test_a_pickle_may_be_text() -> None:
    assert pytables.unpickle(pickle.dumps(["a"], protocol=0).decode("latin-1")) == ["a"]


class Dangerous:
    """An object whose pickle runs a command when it is loaded."""

    def __reduce__(self) -> tuple:
        return os.system, ("echo loaded > loaded.txt",)


@pytest.mark.parametrize("protocol", [0, 2, 5])
def test_a_pickle_cannot_run_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, protocol: int
) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SourceError, match="the pickle refers to"):
        pytables.unpickle(pickle.dumps(Dangerous(), protocol=protocol))
    assert not (tmp_path / "loaded.txt").exists()


@pytest.mark.parametrize(
    "value", [np.array([1, 2]), np.float64(1.5), Path("a"), Group("a", "/a"), 1 + 2j, print]
)
def test_a_pickle_of_an_object_is_refused(value: object) -> None:
    with pytest.raises(SourceError, match="a pickled value cannot be loaded"):
        pytables.unpickle(pickle.dumps(value))


@pytest.mark.parametrize("data", [b"", b"not a pickle", b"\x80\x05", b"(lp0\nVname"])
def test_a_damaged_pickle_is_refused(data: bytes) -> None:
    with pytest.raises(SourceError, match="a pickled value cannot be loaded"):
        pytables.unpickle(data)
