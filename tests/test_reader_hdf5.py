"""Reading HDF5 files and the netCDF-4 files stored in them."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import h5py
import netCDF4
import numpy as np
import pytest
import xarray as xr
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from hypothesis.extra import numpy as hnp

from coati import cf
from coati.errors import SourceError
from coati.readers import open_dataset
from coati.readers.hdf5 import open_hdf5
from support import files

# -- netCDF-4 ---------------------------------------------------------------------------------


@pytest.fixture
def netcdf(tmp_path: Path) -> Path:
    path = tmp_path / "data.nc"
    with netCDF4.Dataset(path, "w") as dataset:
        dataset.title = "A file"
        dataset.setncattr("numbers", np.array([1.5, 2.5]))
        dataset.setncattr("one", np.int32(7))
        dataset.setncattr_string("names", ["a", "b"])
        dataset.setncattr_string("single", ["only"])
        dataset.createDimension("time", None)
        dataset.createDimension("x", 3)
        dataset.createDimension("unused", 4)
        x = dataset.createVariable("x", "f8", ("x",))
        x[:] = [10.0, 20.0, 30.0]
        x.units = "m"
        values = dataset.createVariable("values", "f4", ("time", "x"), fill_value=-1.0)
        values[:] = [[1, 2, 3], [4, -1, 6]]
        values.long_name = "Values"
        labels = dataset.createVariable("labels", str, ("x",))
        labels[:] = np.array(["one", "zwei", "三"], dtype=object)
        scalar = dataset.createVariable("scalar", "i4", ())
        scalar[...] = 42
        group = dataset.createGroup("inner")
        group.note = "nested"
        group.createDimension("y", 2)
        inner = group.createVariable("matrix", "i2", ("y", "x"))
        inner[:] = [[1, 2, 3], [4, 5, 6]]
        deep = group.createGroup("deep")
        deep.createVariable("flag", "i1", ())[...] = 1
    return path


def test_the_format_is_recognised(netcdf: Path) -> None:
    with open_dataset(netcdf) as dataset:
        assert dataset.format == "netcdf4"
        assert dataset.source == netcdf
        assert dataset.warnings == []
        assert "netcdf" in dataset.properties["_NCProperties"]


def test_attributes(netcdf: Path) -> None:
    with open_dataset(netcdf) as dataset:
        attributes = dataset.attributes
        assert list(attributes) == ["title", "numbers", "one", "names", "single"]
        assert attributes["title"] == "A file"
        assert attributes["numbers"].tolist() == [1.5, 2.5]
        assert attributes["one"] == 7
        assert type(attributes["one"]) is int
        assert attributes["names"] == ["a", "b"]


def test_a_list_of_one_text_stays_a_list(netcdf: Path) -> None:
    with open_dataset(netcdf) as dataset:
        assert dataset.attributes["single"] == ["only"]


def test_bookkeeping_is_no_attribute(netcdf: Path) -> None:
    with open_dataset(netcdf) as dataset:
        for group in dataset.walk():
            for holder in (group, *group.variables.values()):
                hidden = {"DIMENSION_LIST", "REFERENCE_LIST", "CLASS", "NAME", "_Netcdf4Dimid"}
                assert not hidden & set(holder.attributes), holder


def test_dimensions(netcdf: Path) -> None:
    with open_dataset(netcdf) as dataset:
        sizes = {name: (item.size, item.unlimited) for name, item in dataset.dimensions.items()}
        assert sizes == {"time": (2, True), "x": (3, False), "unused": (4, False)}
        assert dataset.groups["inner"].dimensions["y"].size == 2


def test_a_dimension_without_values_is_no_variable(netcdf: Path) -> None:
    with open_dataset(netcdf) as dataset:
        assert set(dataset.variables) == {"x", "values", "labels", "scalar"}


def test_variables(netcdf: Path) -> None:
    with open_dataset(netcdf) as dataset:
        values = dataset.variables["values"]
        assert values.path == "/values"
        assert values.dimensions == ("time", "x")
        assert values.shape == (2, 3)
        assert values.type_name == "float32"
        assert values.size == 6
        assert values.ndim == 2
        assert values.attributes == {"_FillValue": -1.0, "long_name": "Values"}
        assert values.read().tolist() == [[1, 2, 3], [4, -1, 6]]
        assert repr(values) == "<Variable /values float32 (time: 2, x: 3)>"
        coordinate = dataset.variables["x"]
        assert coordinate.dimensions == ("x",)
        assert coordinate.read().tolist() == [10.0, 20.0, 30.0]
        scalar = dataset.variables["scalar"]
        assert scalar.dimensions == ()
        assert scalar.shape == ()
        assert scalar.size == 1
        assert scalar.read().item() == 42


def test_text(netcdf: Path) -> None:
    with open_dataset(netcdf) as dataset:
        labels = dataset.variables["labels"]
        assert labels.type_name == "string"
        assert labels.dtype == np.dtype(object)
        assert labels.read().tolist() == ["one", "zwei", "三"]


def test_groups(netcdf: Path) -> None:
    with open_dataset(netcdf) as dataset:
        inner = dataset.groups["inner"]
        assert inner.path == "/inner"
        assert inner.parent is dataset
        assert inner.attributes == {"note": "nested"}
        matrix = inner.variables["matrix"]
        assert matrix.path == "/inner/matrix"
        assert matrix.dimensions == ("y", "x")
        assert [group.path for group in dataset.walk()] == ["/", "/inner", "/inner/deep"]


def test_paths(netcdf: Path) -> None:
    with open_dataset(netcdf) as dataset:
        inner = dataset.groups["inner"]
        assert dataset.get("inner/matrix") is inner.variables["matrix"]
        assert dataset.get("/inner/deep/flag").read().item() == 1
        assert inner.get("/values") is dataset.variables["values"]
        assert inner.get("deep") is inner.groups["deep"]
        assert dataset.variable("inner/matrix") is inner.variables["matrix"]
        assert dataset.variable("inner") is None
        assert dataset.group("inner") is inner
        assert dataset.group("values") is None
        assert dataset.get("missing") is None
        assert dataset.get("inner/missing/matrix") is None
        assert inner.groups["deep"].root is dataset
        assert "inner/matrix" in dataset
        assert "inner/missing" not in dataset
        assert 7 not in dataset


def test_a_dimension_is_visible_in_the_groups_below(netcdf: Path) -> None:
    with open_dataset(netcdf) as dataset:
        deep = dataset.groups["inner"].groups["deep"]
        assert deep.dimension("x").size == 3
        assert deep.dimension("y").size == 2
        assert deep.dimension("missing") is None
        assert dataset.dimension("y") is None


def test_a_closed_dataset_cannot_be_read(netcdf: Path) -> None:
    dataset = open_dataset(netcdf)
    assert not dataset.closed
    dataset.close()
    assert dataset.closed
    dataset.close()
    with pytest.raises(SourceError, match="/values cannot be read"):
        dataset.variables["values"].read()


def test_a_variable_that_shares_the_name_of_a_dimension(tmp_path: Path) -> None:
    path = tmp_path / "data.nc"
    with netCDF4.Dataset(path, "w") as dataset:
        dataset.createDimension("x", 2)
        dataset.createDimension("y", 3)
        dataset.createVariable("x", "i4", ("y", "x"))[:] = [[1, 2], [3, 4], [5, 6]]
    with open_dataset(path) as dataset:
        assert set(dataset.variables) == {"x"}
        assert dataset.variables["x"].path == "/x"
        assert dataset.variables["x"].dimensions == ("y", "x")
        assert dataset.dimensions["x"].size == 2


def test_characters(tmp_path: Path) -> None:
    path = tmp_path / "data.nc"
    with netCDF4.Dataset(path, "w", format="NETCDF4_CLASSIC") as dataset:
        dataset.createDimension("x", 2)
        dataset.createDimension("length", 4)
        names = dataset.createVariable("names", "S1", ("x", "length"))
        names._Encoding = "none"
        names[:] = np.array([list("ab\0\0"), list("cdef")], dtype="S1")
    with open_dataset(path) as dataset:
        names = dataset.variables["names"]
        assert names.type_name == "char"
        assert names.shape == (2, 4)
        found = cf.decode(names)
        assert found.values.tolist() == ["ab", "cdef"]
        assert found.dimensions == ("x",)


def test_enumerations(tmp_path: Path) -> None:
    path = tmp_path / "data.nc"
    with netCDF4.Dataset(path, "w") as dataset:
        kind = dataset.createEnumType("i1", "kind", {"off": 0, "on": 1, "broken": 9})
        dataset.createDimension("x", 3)
        dataset.createVariable("state", kind, ("x",))[:] = [1, 0, 9]
    with open_dataset(path) as dataset:
        state = dataset.variables["state"]
        assert state.enumeration == {"off": 0, "on": 1, "broken": 9}
        assert state.type_name == "int8"
        assert state.read().tolist() == [1, 0, 9]


def test_variable_lengths(tmp_path: Path) -> None:
    path = tmp_path / "data.nc"
    with netCDF4.Dataset(path, "w") as dataset:
        ragged = dataset.createVLType("i4", "ragged")
        dataset.createDimension("x", 2)
        variable = dataset.createVariable("lists", ragged, ("x",))
        variable[0] = np.array([1, 2, 3], dtype="i4")
        variable[1] = np.array([4], dtype="i4")
    with open_dataset(path) as dataset:
        lists = dataset.variables["lists"]
        assert lists.type_name == "vlen<int32>"
        assert [item.tolist() for item in lists.read()] == [[1, 2, 3], [4]]


def test_compound_types(tmp_path: Path) -> None:
    path = tmp_path / "data.nc"
    record = np.dtype([("index", "i4"), ("value", "f8")])
    with netCDF4.Dataset(path, "w") as dataset:
        kind = dataset.createCompoundType(record, "record")
        dataset.createDimension("x", 2)
        dataset.createVariable("records", kind, ("x",))[:] = np.array(
            [(1, 0.5), (2, 1.5)], dtype=record
        )
    with open_dataset(path) as dataset:
        records = dataset.variables["records"]
        assert records.type_name == "compound"
        assert records.read()["value"].tolist() == [0.5, 1.5]


# -- plain HDF5 -------------------------------------------------------------------------------


@pytest.fixture
def plain(tmp_path: Path) -> Path:
    path = tmp_path / "data.h5"
    with h5py.File(path, "w") as file:
        file.attrs["text"] = "scalar text"
        file.attrs["bytes"] = np.bytes_("fixed")
        file.attrs["number"] = 1.5
        file.attrs["flag"] = np.bool_(True)
        file.attrs["nothing"] = h5py.Empty("f8")
        file.attrs["list"] = [1, 2, 3]
        file.attrs["texts"] = np.array(["a", "b"], dtype=h5py.string_dtype())
        file.attrs["CLASS"] = np.bytes_("GROUP")
        file.create_dataset("numbers", data=np.arange(6.0).reshape(2, 3))
        file.create_dataset("scalar", data=3.5)
        file.create_dataset("text", data="one text")
        file.create_dataset("texts", data=["a", "bc"])
        file.create_dataset("fixed", data=np.array([b"ab", b"c"], dtype="S4"))
        file.create_dataset("letters", data=np.array([b"a", b"b"], dtype="S1"))
        file.create_dataset("truth", data=np.array([True, False]))
        file.create_dataset("empty", data=h5py.Empty("f8"))
        file.create_dataset("none", shape=(0, 3), dtype="f8")
        file.create_dataset("opaque", data=np.array([b"\x00\x01"], dtype="V2"))
        file.create_dataset("group/nested/deep", data=[1, 2])
    return path


def test_a_plain_file_is_hdf5(plain: Path) -> None:
    with open_dataset(plain) as dataset:
        assert dataset.format == "hdf5"
        assert dataset.dimensions == {}
        assert dataset.properties == {}


def test_attributes_of_a_plain_file(plain: Path) -> None:
    with open_dataset(plain) as dataset:
        assert dataset.attributes["text"] == "scalar text"
        assert dataset.attributes["bytes"] == "fixed"
        assert dataset.attributes["number"] == 1.5
        assert dataset.attributes["flag"] is True
        assert dataset.attributes["nothing"] is None
        assert dataset.attributes["list"].tolist() == [1, 2, 3]
        assert dataset.attributes["texts"] == ["a", "b"]


def test_the_class_of_another_library_is_an_attribute(plain: Path) -> None:
    with open_dataset(plain) as dataset:
        assert dataset.attributes["CLASS"] == "GROUP"


def test_axes_without_dimensions(plain: Path) -> None:
    with open_dataset(plain) as dataset:
        numbers = dataset.variables["numbers"]
        assert numbers.dimensions == (None, None)
        assert numbers.read().tolist() == [[0, 1, 2], [3, 4, 5]]
        assert repr(numbers) == "<Variable /numbers float64 (?: 2, ?: 3)>"
        assert dataset.variables["scalar"].dimensions == ()


def test_values_of_a_plain_file(plain: Path) -> None:
    with open_dataset(plain) as dataset:
        read = {name: variable.read() for name, variable in dataset.variables.items()}
        assert read["scalar"].item() == 3.5
        assert read["text"].item() == "one text"
        assert read["texts"].tolist() == ["a", "bc"]
        assert read["fixed"].tolist() == ["ab", "c"]
        assert read["truth"].tolist() == [True, False]
        assert read["none"].shape == (0, 3)
        assert dataset.variables["truth"].type_name == "bool"
        assert dataset.variables["fixed"].type_name == "string"
        assert dataset.variables["opaque"].type_name == "opaque"
        assert dataset.variable("group/nested/deep").read().tolist() == [1, 2]


def test_single_bytes_without_dimensions_are_text_not_characters(plain: Path) -> None:
    with open_dataset(plain) as dataset:
        letters = dataset.variables["letters"]
        assert letters.type_name == "string"
        assert cf.decode(letters).values.tolist() == ["a", "b"]


def test_a_dataset_without_a_dataspace(plain: Path) -> None:
    with open_dataset(plain) as dataset:
        empty = dataset.variables["empty"]
        assert empty.shape == ()
        assert np.ma.is_masked(empty.read())


def test_scales_of_a_plain_file_name_the_axes(tmp_path: Path) -> None:
    path = tmp_path / "data.h5"
    with h5py.File(path, "w") as file:
        file.create_dataset("x", data=[1.0, 2.0])
        file["x"].make_scale("x")
        file.create_dataset("values", data=[[1, 2], [3, 4]])
        file["values"].dims[1].attach_scale(file["x"])
    with open_dataset(path) as dataset:
        assert dataset.dimensions["x"].size == 2
        assert dataset.variables["x"].dimensions == ("x",)
        assert dataset.variables["x"].attributes == {}
        assert dataset.variables["values"].dimensions == (None, "x")


def test_references(tmp_path: Path) -> None:
    path = tmp_path / "data.h5"
    with h5py.File(path, "w") as file:
        target = file.create_dataset("target", data=[1])
        file.attrs["pointer"] = target.ref
        file.attrs["pointers"] = np.array([target.ref, file.ref], dtype=h5py.ref_dtype)
        pointers = file.create_dataset("pointers", (2,), dtype=h5py.ref_dtype)
        pointers[0] = target.ref
    with open_dataset(path) as dataset:
        assert dataset.attributes["pointer"] == "/target"
        assert dataset.attributes["pointers"] == ["/target", "/"]
        assert dataset.variables["pointers"].type_name == "reference"
        assert dataset.variables["pointers"].read().tolist() == ["/target", None]


# -- links ------------------------------------------------------------------------------------


def test_a_link_into_another_file_is_not_followed(tmp_path: Path) -> None:
    secret = tmp_path / "secret.h5"
    with h5py.File(secret, "w") as file:
        file.create_dataset("password", data="hunter2")
    path = tmp_path / "data.h5"
    with h5py.File(path, "w") as file:
        file["outside"] = h5py.ExternalLink("secret.h5", "/password")
        file.create_dataset("inside", data=[1])
    with open_dataset(path) as dataset:
        assert set(dataset.variables) == {"inside"}
        assert dataset.warnings == [
            "/outside is a link into the file 'secret.h5'; it is not followed"
        ]


def test_a_link_that_leads_nowhere(tmp_path: Path) -> None:
    path = tmp_path / "data.h5"
    with h5py.File(path, "w") as file:
        file["dangling"] = h5py.SoftLink("/nowhere")
        file.create_dataset("inside", data=[1])
    with open_dataset(path) as dataset:
        assert set(dataset.variables) == {"inside"}
        assert len(dataset.warnings) == 1
        assert dataset.warnings[0].startswith("/dangling cannot be opened")


def test_links_that_form_a_circle_end_the_walk(tmp_path: Path) -> None:
    path = tmp_path / "data.h5"
    with h5py.File(path, "w") as file:
        child = file.create_group("parent/child")
        child["back"] = file["parent"]
        child["soft"] = h5py.SoftLink("/parent")
        file["parent"].create_dataset("values", data=[1])
    with open_dataset(path) as dataset:
        assert [group.path for group in dataset.walk()] == ["/", "/parent", "/parent/child"]
        assert sorted(dataset.warnings) == [
            "/parent/child/back is the group /parent, which is already listed; it is not repeated",
            "/parent/child/soft is the group /parent, which is already listed; it is not repeated",
        ]


def test_a_link_within_the_file_is_followed(tmp_path: Path) -> None:
    path = tmp_path / "data.h5"
    with h5py.File(path, "w") as file:
        file.create_dataset("values", data=[1, 2])
        file["alias"] = h5py.SoftLink("/values")
    with open_dataset(path) as dataset:
        assert dataset.variables["alias"].read().tolist() == [1, 2]
        assert dataset.warnings == []


# -- the order of what a file holds -----------------------------------------------------------


def ordered(path: Path, **options: Any) -> Path:
    with h5py.File(path, "w", **options) as file:
        for name in ("zeta", "alpha", "mid"):
            file.create_dataset(name, data=[1.0]).attrs.update({"z": 1, "a": 2})
            file.create_group(f"group_{name}")
        file.attrs.update({"z": 1, "a": 2})
    return path


def test_a_file_that_records_the_order_of_creation_is_read_in_that_order(tmp_path: Path) -> None:
    with open_dataset(ordered(tmp_path / "data.h5", track_order=True)) as dataset:
        assert list(dataset.variables) == ["zeta", "alpha", "mid"]
        assert list(dataset.groups) == ["group_zeta", "group_alpha", "group_mid"]
        assert list(dataset.attributes) == ["z", "a"]


def test_a_file_that_does_not_is_read_in_the_order_of_the_names(tmp_path: Path) -> None:
    with open_dataset(ordered(tmp_path / "data.h5", track_order=False)) as dataset:
        assert list(dataset.variables) == ["alpha", "mid", "zeta"]
        assert list(dataset.groups) == ["group_alpha", "group_mid", "group_zeta"]
        assert list(dataset.attributes) == ["a", "z"]
        assert list(dataset.variables["zeta"].attributes) == ["a", "z"]


def test_a_netcdf_file_is_read_in_the_order_of_creation(tmp_path: Path) -> None:
    # The netCDF library records the order; what is read does not depend on the version of h5py.
    path = tmp_path / "data.nc"
    with netCDF4.Dataset(path, "w") as dataset:
        dataset.setncatts({"z": 1, "a": 2})
        dataset.createDimension("x", 2)
        for name in ("zeta", "alpha", "mid"):
            dataset.createVariable(name, "f8", ("x",)).setncatts({"zz": 1, "aa": 2})
        for name in ("second", "first"):
            dataset.createGroup(name)
    with open_dataset(path) as dataset:
        assert list(dataset.variables) == ["zeta", "alpha", "mid"]
        assert list(dataset.groups) == ["second", "first"]
        assert list(dataset.attributes) == ["z", "a"]
        assert list(dataset.variables["zeta"].attributes) == ["zz", "aa"]


# -- failures ---------------------------------------------------------------------------------


def test_a_damaged_file(tmp_path: Path) -> None:
    path = files.calliope06(tmp_path / "data.nc")
    content = path.read_bytes()
    path.write_bytes(content[:4000])
    with pytest.raises(SourceError, match="cannot be opened as HDF5"):
        open_hdf5(path)


def read_all(path: Path) -> None:
    with open_dataset(path) as dataset:
        for group in dataset.walk():
            for variable in group.variables.values():
                variable.read()


def test_a_file_cut_short_anywhere_is_refused(tmp_path: Path, netcdf: Path) -> None:
    content = netcdf.read_bytes()
    read_all(netcdf)
    path = tmp_path / "cut.nc"
    for length in range(0, len(content), len(content) // 150):
        path.write_bytes(content[:length])
        with pytest.raises(SourceError):
            read_all(path)


def test_a_file_that_is_no_hdf5(tmp_path: Path) -> None:
    path = tmp_path / "data.h5"
    path.write_text("not a data file")
    with pytest.raises(SourceError, match=r"data\.h5: cannot be opened as HDF5"):
        open_hdf5(path)


# -- against xarray ---------------------------------------------------------------------------

names = st.text(st.characters(min_codepoint=97, max_codepoint=122), min_size=1, max_size=6)
types = st.sampled_from(["f8", "f4", "i8", "i2", "u1", "bool", "str", "time"])


@st.composite
def datasets(draw: st.DrawFn) -> xr.Dataset:
    """Draw a dataset of a few variables over two dimensions."""
    sizes = {"x": draw(st.integers(1, 4)), "t": draw(st.integers(1, 4))}
    variables: dict[str, Any] = {}
    for name in draw(st.lists(names, min_size=1, max_size=4, unique=True)):
        dims = tuple(draw(st.lists(st.sampled_from(["x", "t"]), max_size=2, unique=True)))
        shape = tuple(sizes[dim] for dim in dims)
        kind = draw(types)
        if kind == "str":
            data: Any = draw(hnp.arrays(object, shape, elements=st.text(max_size=5)))
        elif kind == "time":
            offsets = draw(hnp.arrays("i8", shape, elements=st.integers(0, 10**6)))
            data = np.datetime64("2000-01-01", "s") + offsets.astype("timedelta64[s]")
            data = data.astype("datetime64[ns]")
        else:
            elements = None if kind.startswith("f") else {"allow_nan": False}
            data = draw(hnp.arrays(kind, shape, elements=elements) if elements is None
                        else hnp.arrays(kind, shape))  # fmt: skip
        variables[f"v_{name}"] = (dims, data)
    return xr.Dataset(variables)


@given(datasets())
@settings(
    max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
def test_what_is_read_is_what_xarray_reads(tmp_path: Path, dataset: xr.Dataset) -> None:
    path = tmp_path / "data.nc"
    dataset.to_netcdf(path, engine="netcdf4")
    with xr.open_dataset(path, engine="netcdf4") as expected, open_dataset(path) as found:
        assert set(found.variables) == set(expected.variables)
        for name, variable in found.variables.items():
            reference = expected.variables[name]
            read = cf.decode(variable)
            assert read.dimensions == reference.dims
            assert read.values.shape == reference.shape
            if reference.dtype.kind == "M":
                expected_values = reference.values.astype("datetime64[us]")
                np.testing.assert_array_equal(np.asarray(read.values), expected_values)
            elif reference.dtype.kind in "OUT":
                assert read.values.tolist() == reference.values.astype(object).tolist()
            else:
                filled = np.ma.filled(read.values.astype(float), np.nan)
                np.testing.assert_array_equal(filled, reference.values.astype(float))
