"""Reading the classic netCDF formats: CDF-1, CDF-2 and CDF-5."""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

import netCDF4
import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from hypothesis.extra import numpy as hnp
from scipy.io import netcdf_file

from coati import cf
from coati.errors import SourceError
from coati.readers import open_dataset
from coati.readers.classic import open_classic

FORMATS = {
    "NETCDF3_CLASSIC": "netcdf3-classic",
    "NETCDF3_64BIT_OFFSET": "netcdf3-64bit-offset",
    "NETCDF3_64BIT_DATA": "netcdf3-64bit-data",
}
CLASSIC_TYPES = ["i1", "i2", "i4", "f4", "f8"]
CDF5_TYPES = [*CLASSIC_TYPES, "u1", "u2", "u4", "i8", "u8"]


def types_of(file_format: str) -> list[str]:
    return CDF5_TYPES if file_format == "NETCDF3_64BIT_DATA" else CLASSIC_TYPES


def numbers(kind: str, shape: tuple[int, ...], seed: int = 0) -> np.ndarray:
    generator = np.random.default_rng(seed)
    if kind[0] in "iu":
        limits = np.iinfo(kind)
        return generator.integers(limits.min, limits.max, size=shape, dtype=kind, endpoint=True)
    return generator.normal(size=shape).astype(kind)


def write(path: Path, file_format: str, records: int) -> dict[str, np.ndarray]:
    """Write a file with variables of every type, with and without records."""
    expected: dict[str, np.ndarray] = {}
    with netCDF4.Dataset(path, "w", format=file_format) as dataset:
        dataset.set_fill_off()
        dataset.title = "A classic file"
        dataset.setncattr("numbers", np.array([1.5, 2.5]))
        dataset.setncattr("one", np.int32(7))
        dataset.createDimension("time", None)
        dataset.createDimension("x", 3)
        dataset.createDimension("y", 2)
        dataset.createDimension("length", 5)
        for kind in types_of(file_format):
            for name, dims in (
                (f"fixed_{kind}", ("x", "y")),
                (f"scalar_{kind}", ()),
                (f"record_{kind}", ("time", "x")),
                (f"series_{kind}", ("time",)),
            ):
                shape = tuple(
                    records if dim == "time" else len(dataset.dimensions[dim]) for dim in dims
                )
                variable = dataset.createVariable(name, kind, dims)
                variable.units = "m"
                variable.setncattr("valid_range", np.array([1, 2], dtype=kind))
                expected[name] = numbers(kind, shape, seed=len(expected))
                if expected[name].size:
                    variable[...] = expected[name]
        labels = dataset.createVariable("labels", "S1", ("x", "length"))
        labels._Encoding = "none"
        expected["labels"] = np.array([list("ab\0\0\0"), list("hello"), list("\0" * 5)], dtype="S1")
        labels[:] = expected["labels"]
    return expected


@pytest.mark.parametrize("file_format", FORMATS)
@pytest.mark.parametrize("records", [0, 1, 5])
def test_every_type_with_and_without_records(
    tmp_path: Path, file_format: str, records: int
) -> None:
    path = tmp_path / "data.nc"
    expected = write(path, file_format, records)
    with open_dataset(path) as dataset:
        assert dataset.format == FORMATS[file_format]
        assert dataset.groups == {}
        assert set(dataset.variables) == set(expected)
        for name, values in expected.items():
            variable = dataset.variables[name]
            read = variable.read()
            assert read.dtype == values.dtype, name
            assert variable.dtype == values.dtype, name
            assert variable.shape == values.shape, name
            assert variable.path == f"/{name}"
            np.testing.assert_array_equal(read, values, err_msg=name)


@pytest.mark.parametrize("file_format", FORMATS)
def test_dimensions_and_attributes(tmp_path: Path, file_format: str) -> None:
    path = tmp_path / "data.nc"
    write(path, file_format, records=4)
    with open_dataset(path) as dataset:
        sizes = {name: (item.size, item.unlimited) for name, item in dataset.dimensions.items()}
        assert sizes == {
            "time": (4, True),
            "x": (3, False),
            "y": (2, False),
            "length": (5, False),
        }
        assert dataset.attributes["title"] == "A classic file"
        assert dataset.attributes["numbers"].tolist() == [1.5, 2.5]
        assert dataset.attributes["one"] == 7
        assert type(dataset.attributes["one"]) is int
        variable = dataset.variables["record_f8"]
        assert variable.dimensions == ("time", "x")
        assert variable.type_name == "float64"
        assert variable.attributes["units"] == "m"
        assert variable.attributes["valid_range"].tolist() == [1.0, 2.0]


@pytest.mark.parametrize("file_format", FORMATS)
@pytest.mark.parametrize("kind", ["i1", "i2", "f8"])
@pytest.mark.parametrize("records", [0, 1, 3])
def test_a_single_record_variable_has_no_padding(
    tmp_path: Path, file_format: str, kind: str, records: int
) -> None:
    path = tmp_path / "data.nc"
    expected = numbers(kind, (records, 3))
    with netCDF4.Dataset(path, "w", format=file_format) as dataset:
        dataset.createDimension("time", None)
        dataset.createDimension("x", 3)
        variable = dataset.createVariable("only", kind, ("time", "x"))
        if records:
            variable[:] = expected
    with open_dataset(path) as dataset:
        np.testing.assert_array_equal(dataset.variables["only"].read(), expected)
        assert dataset.dimensions["time"].size == records


def test_characters_become_text(tmp_path: Path) -> None:
    path = tmp_path / "data.nc"
    write(path, "NETCDF3_CLASSIC", records=1)
    with open_dataset(path) as dataset:
        labels = dataset.variables["labels"]
        assert labels.type_name == "char"
        found = cf.decode(labels)
        assert found.values.tolist() == ["ab", "hello", ""]
        assert found.dimensions == ("x",)


def test_times(tmp_path: Path) -> None:
    path = tmp_path / "data.nc"
    with netCDF4.Dataset(path, "w", format="NETCDF3_CLASSIC") as dataset:
        dataset.createDimension("time", None)
        time = dataset.createVariable("time", "i4", ("time",))
        time.units = "hours since 2005-01-01 00:00:00"
        time.calendar = "proleptic_gregorian"
        time[:] = [0, 1, 2]
    with open_dataset(path) as dataset:
        found = cf.decode(dataset.variables["time"])
        assert found.type_name == "datetime"
        assert found.values[2] == np.datetime64("2005-01-01T02:00:00", "us")


def test_a_file_of_another_writer(tmp_path: Path) -> None:
    path = tmp_path / "data.nc"
    with netcdf_file(path, "w", version=2) as file:
        file.history = "made by scipy"
        file.createDimension("t", None)
        file.createDimension("n", 4)
        values = file.createVariable("values", "f8", ("t", "n"))
        values[:] = np.arange(12.0).reshape(3, 4)
        values.units = "MW"
        counts = file.createVariable("counts", "i2", ("t",))
        counts[:] = np.array([1, 2, 3], dtype="i2")
    with open_dataset(path) as dataset:
        assert dataset.format == "netcdf3-64bit-offset"
        assert dataset.attributes == {"history": "made by scipy"}
        assert dataset.variables["values"].read().tolist() == np.arange(12.0).reshape(3, 4).tolist()
        assert dataset.variables["counts"].read().tolist() == [1, 2, 3]
        assert dataset.variables["values"].attributes == {"units": "MW"}


def test_an_empty_file_of_the_format(tmp_path: Path) -> None:
    path = tmp_path / "data.nc"
    netCDF4.Dataset(path, "w", format="NETCDF3_CLASSIC").close()
    with open_dataset(path) as dataset:
        assert dataset.attributes == {}
        assert dataset.dimensions == {}
        assert dataset.variables == {}


def test_a_closed_dataset_cannot_be_read(tmp_path: Path) -> None:
    path = tmp_path / "data.nc"
    write(path, "NETCDF3_CLASSIC", records=1)
    dataset = open_dataset(path)
    variable = dataset.variables["fixed_f8"]
    dataset.close()
    assert dataset.closed
    with pytest.raises(SourceError, match="'fixed_f8' cannot be read: the file is closed"):
        variable.read()


def test_what_is_read_does_not_depend_on_the_file_staying_open(tmp_path: Path) -> None:
    path = tmp_path / "data.nc"
    expected = write(path, "NETCDF3_CLASSIC", records=2)
    with open_dataset(path) as dataset:
        read = dataset.variables["record_f8"].read()
    np.testing.assert_array_equal(read, expected["record_f8"])
    assert read.dtype.isnative


# -- damaged files ----------------------------------------------------------------------------


@pytest.fixture
def valid(tmp_path: Path) -> bytes:
    path = tmp_path / "valid.nc"
    write(path, "NETCDF3_CLASSIC", records=2)
    return path.read_bytes()


def read_all(path: Path) -> None:
    with open_classic(path) as dataset:
        for variable in dataset.variables.values():
            variable.read()


def refused(tmp_path: Path, content: bytes) -> str:
    path = tmp_path / "damaged.nc"
    path.write_bytes(content)
    with pytest.raises(SourceError) as caught:
        read_all(path)
    return str(caught.value)


def test_a_file_cut_short_in_the_header(tmp_path: Path, valid: bytes) -> None:
    for length in (4, 8, 20, 60, 200):
        assert "the header ends unexpectedly" in refused(tmp_path, valid[:length])


def test_a_file_cut_short_in_the_values(tmp_path: Path, valid: bytes) -> None:
    assert "extends beyond the end of the file" in refused(tmp_path, valid[:-40])


def test_a_file_cut_short_anywhere_is_refused(tmp_path: Path, valid: bytes) -> None:
    path = tmp_path / "damaged.nc"
    accepted = []
    for length in range(len(valid)):
        path.write_bytes(valid[:length])
        try:
            read_all(path)
        except SourceError:
            continue
        accepted.append(length)
    assert accepted == []


@given(st.data())
@settings(
    max_examples=400, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
def test_a_damaged_file_is_refused_or_read(
    tmp_path: Path, valid: bytes, data: st.DataObject
) -> None:
    # Whatever a file holds, the reader ends with values or with an error of its own.
    damaged = bytearray(valid)
    for _ in range(data.draw(st.integers(1, 4))):
        position = data.draw(st.integers(0, len(valid) - 1))
        damaged[position] = data.draw(st.integers(0, 255))
    path = tmp_path / "damaged.nc"
    path.write_bytes(bytes(damaged))
    message = None
    try:
        read_all(path)
    except SourceError as error:
        message = str(error)
    assert message is None or message.startswith(str(path))


def test_a_count_that_is_negative(tmp_path: Path, valid: bytes) -> None:
    damaged = valid[:12] + struct.pack(">i", -5) + valid[16:]
    assert "a negative count (-5)" in refused(tmp_path, damaged)


def test_a_count_that_is_larger_than_the_file(tmp_path: Path, valid: bytes) -> None:
    damaged = valid[:12] + struct.pack(">i", 2**31 - 1) + valid[16:]
    assert "the header ends unexpectedly" in refused(tmp_path, damaged)


def test_a_tag_that_is_unknown(tmp_path: Path, valid: bytes) -> None:
    damaged = valid[:8] + struct.pack(">i", 0x7F) + valid[12:]
    assert "the list of dimensions starts with the tag 0x7f" in refused(tmp_path, damaged)


def test_a_type_that_is_unknown(tmp_path: Path) -> None:
    header = b"CDF\x01" + struct.pack(">iii", 0, 0, 0)  # no records, no dimensions
    attribute = struct.pack(">ii", 0x0C, 1) + struct.pack(">i", 1) + b"a\0\0\0"
    damaged = header + attribute + struct.pack(">ii", 99, 0) + struct.pack(">ii", 0, 0)
    assert "the unknown type 99" in refused(tmp_path, damaged)


def test_a_type_of_cdf_5_in_an_older_format(tmp_path: Path) -> None:
    header = b"CDF\x01" + struct.pack(">iii", 0, 0, 0)
    attribute = struct.pack(">ii", 0x0C, 1) + struct.pack(">i", 1) + b"a\0\0\0"
    damaged = header + attribute + struct.pack(">ii", 10, 0) + struct.pack(">ii", 0, 0)
    assert "the unknown type 10" in refused(tmp_path, damaged)


def test_a_variable_of_a_dimension_that_does_not_exist(tmp_path: Path) -> None:
    header = b"CDF\x01" + struct.pack(">i", 0)
    dimensions = (
        struct.pack(">ii", 0x0A, 1) + struct.pack(">i", 1) + b"x\0\0\0" + struct.pack(">i", 2)
    )
    attributes = struct.pack(">ii", 0, 0)
    variable = struct.pack(">ii", 0x0B, 1) + struct.pack(">i", 1) + b"v\0\0\0"
    variable += struct.pack(">ii", 1, 7) + struct.pack(">ii", 0, 0) + struct.pack(">iii", 6, 16, 0)
    message = refused(tmp_path, header + dimensions + attributes + variable)
    assert "the variable 'v' refers to a dimension that does not exist" in message


def test_two_unlimited_dimensions(tmp_path: Path) -> None:
    header = b"CDF\x01" + struct.pack(">i", 0)
    dimensions = struct.pack(">ii", 0x0A, 2)
    for name in (b"a", b"b"):
        dimensions += struct.pack(">i", 1) + name + b"\0\0\0" + struct.pack(">i", 0)
    message = refused(tmp_path, header + dimensions + struct.pack(">iiii", 0, 0, 0, 0))
    assert "more than one unlimited dimension" in message


def test_a_file_of_another_format(tmp_path: Path) -> None:
    assert "not a classic netCDF file" in refused(tmp_path, b"CDF\x03" + bytes(32))
    assert "not a classic netCDF file" in refused(tmp_path, b"HDF5" + bytes(32))


def test_a_number_of_records_that_is_not_stated(tmp_path: Path) -> None:
    path = tmp_path / "data.nc"
    with netCDF4.Dataset(path, "w", format="NETCDF3_CLASSIC") as dataset:
        dataset.createDimension("time", None)
        dataset.createVariable("a", "f8", ("time",))[:] = [1.0, 2.0, 3.0]
        dataset.createVariable("b", "i4", ("time",))[:] = [4, 5, 6]
    content = path.read_bytes()
    path.write_bytes(content[:4] + b"\xff\xff\xff\xff" + content[8:])
    with open_dataset(path) as dataset:
        assert dataset.dimensions["time"].size == 3
        assert dataset.variables["a"].read().tolist() == [1.0, 2.0, 3.0]
        assert dataset.variables["b"].read().tolist() == [4, 5, 6]


# -- against the netCDF library ---------------------------------------------------------------


@st.composite
def described(draw: st.DrawFn) -> tuple[str, int, list[tuple[str, str, tuple[str, ...], Any]]]:
    """Draw a format, a number of records and a few variables."""
    file_format = draw(st.sampled_from(sorted(FORMATS)))
    records = draw(st.integers(0, 4))
    sizes = {"time": records, "x": draw(st.integers(1, 3)), "y": draw(st.integers(1, 3))}
    variables = []
    for position in range(draw(st.integers(1, 5))):
        kind = draw(st.sampled_from(types_of(file_format)))
        inner = tuple(draw(st.lists(st.sampled_from(["x", "y"]), max_size=2, unique=True)))
        dims = ("time", *inner) if draw(st.booleans()) else inner
        shape = tuple(sizes[dim] for dim in dims)
        values = draw(hnp.arrays(kind, shape))
        variables.append((f"v{position}", kind, dims, values))
    return file_format, records, variables


@given(described())
@settings(
    max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
def test_what_is_read_is_what_the_netcdf_library_reads(tmp_path: Path, drawn: Any) -> None:
    file_format, _, variables = drawn
    path = tmp_path / "data.nc"
    with netCDF4.Dataset(path, "w", format=file_format) as dataset:
        dataset.createDimension("time", None)
        dataset.createDimension(
            "x", max(1, *(v[3].shape[v[2].index("x")] for v in variables if "x" in v[2]), 1)
        )
        dataset.createDimension(
            "y", max(1, *(v[3].shape[v[2].index("y")] for v in variables if "y" in v[2]), 1)
        )
        for name, kind, dims, values in variables:
            variable = dataset.createVariable(name, kind, dims)
            variable.set_auto_maskandscale(False)
            if values.size:
                variable[...] = values
    with netCDF4.Dataset(path) as expected, open_dataset(path) as found:
        expected.set_auto_maskandscale(False)
        assert list(found.variables) == list(expected.variables)
        for name, variable in found.variables.items():
            reference = np.asarray(expected.variables[name][...])
            read = variable.read()
            assert read.shape == reference.shape, name
            np.testing.assert_array_equal(read, reference, err_msg=name)
