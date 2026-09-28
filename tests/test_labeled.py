"""Arrays with names for their axes and labels for their positions."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from coati.errors import ExtractionError
from coati.labeled import LabeledArray, finite, labels_of, numbers_of, texts_of, weights_of
from coati.readers import open_dataset
from support import files

NAN = float("nan")


@pytest.fixture
def array() -> LabeledArray:
    values = np.array(
        [[[1.0, 2.0], [NAN, NAN]], [[NAN, 4.0], [5.0, NAN]], [[NAN, NAN], [NAN, NAN]]]
    )
    labels = {"nodes": ("a", "b", "c"), "techs": ("pv", "gas"), "time": ("t0", "t1")}
    return LabeledArray(values, ("nodes", "techs", "time"), labels)


def test_the_axes_must_fit_the_values() -> None:
    with pytest.raises(ValueError, match="2 axes but 1 names"):
        LabeledArray(np.zeros((2, 2)), ("x",), {"x": ("a", "b")})
    with pytest.raises(ValueError, match="the axis 'x' has labels for another length"):
        LabeledArray(np.zeros(2), ("x",), {"x": ("a",)})


def test_axes(array: LabeledArray) -> None:
    assert array.axis("techs") == 1
    assert "time" in array
    assert "costs" not in array
    with pytest.raises(ExtractionError, match="no axis 'costs' among nodes, techs, time"):
        array.axis("costs")


def test_adding_up(array: LabeledArray) -> None:
    total = array.sum("time")
    assert total.dims == ("nodes", "techs")
    assert total.labels == {"nodes": ("a", "b", "c"), "techs": ("pv", "gas")}
    np.testing.assert_array_equal(total.values, [[3.0, NAN], [4.0, 5.0], [NAN, NAN]])


def test_adding_up_along_several_axes(array: LabeledArray) -> None:
    np.testing.assert_array_equal(array.sum("time", "techs").values, [3.0, 9.0, NAN])
    assert array.sum("nodes", "techs", "time").values == 12.0
    assert array.sum("nodes", "techs", "time").dims == ()


def test_what_has_no_value_adds_up_to_no_value_not_to_zero(array: LabeledArray) -> None:
    assert np.isnan(array.sum("time").values[0, 1])
    assert np.isnan(array.sum("techs", "time").values[2])


def test_an_axis_that_is_not_there_is_skipped(array: LabeledArray) -> None:
    assert array.sum("costs") is array
    assert array.max("costs") is array
    np.testing.assert_array_equal(array.sum("costs", "time").values, array.sum("time").values)
    assert array.scale("costs", np.ones(3)) is array


def test_the_largest(array: LabeledArray) -> None:
    largest = array.max("time")
    np.testing.assert_array_equal(largest.values, [[2.0, NAN], [4.0, 5.0], [NAN, NAN]])
    assert array.max("nodes", "techs", "time").values == 5.0


def test_the_largest_of_negative_numbers() -> None:
    array = LabeledArray(
        np.array([[-3.0, -1.0], [NAN, NAN]]), ("x", "y"), {"x": ("a", "b"), "y": ("c", "d")}
    )
    np.testing.assert_array_equal(array.max("y").values, [-1.0, NAN])


def test_selecting(array: LabeledArray) -> None:
    part = array.select("nodes", "b")
    assert part.dims == ("techs", "time")
    np.testing.assert_array_equal(part.values, [[NAN, 4.0], [5.0, NAN]])
    assert array.select("nodes", "b").select("techs", "gas").select("time", "t0").values == 5.0
    with pytest.raises(ExtractionError, match="no 'z' on the axis 'nodes'"):
        array.select("nodes", "z")
    with pytest.raises(ExtractionError, match="no 'a' on the axis 'costs'"):
        array.select("costs", "a")


def test_taking(array: LabeledArray) -> None:
    part = array.take("nodes", ["c", "a", "z"])
    assert part.dims == array.dims
    assert part.labels["nodes"] == ("c", "a")
    np.testing.assert_array_equal(part.values[1], array.values[0])
    assert array.take("nodes", []).values.shape == (0, 2, 2)


def test_scaling(array: LabeledArray) -> None:
    scaled = array.scale("time", np.array([1.0, 10.0]))
    np.testing.assert_array_equal(scaled.values[0], [[1.0, 20.0], [NAN, NAN]])
    scaled = array.scale("nodes", np.array([1.0, 2.0, 3.0]))
    np.testing.assert_array_equal(scaled.values[1], [[NAN, 8.0], [10.0, NAN]])


def test_magnitudes() -> None:
    array = LabeledArray(np.array([-1.0, NAN, 2.0]), ("x",), {"x": ("a", "b", "c")})
    np.testing.assert_array_equal(array.absolute().values, [1.0, NAN, 2.0])


def test_a_series_counts_what_has_no_value_as_zero(array: LabeledArray) -> None:
    assert array.series("time").tolist() == [6.0, 6.0]
    assert array.select("nodes", "c").series("time").tolist() == [0.0, 0.0]
    assert array.series("nodes").tolist() == [3.0, 9.0, 0.0]
    with pytest.raises(ExtractionError, match="no axis 'costs'"):
        array.series("costs")


def test_the_elements_that_have_a_value(array: LabeledArray) -> None:
    assert list(array.items()) == [
        (("a", "pv", "t0"), 1.0),
        (("a", "pv", "t1"), 2.0),
        (("b", "pv", "t1"), 4.0),
        (("b", "gas", "t0"), 5.0),
    ]
    assert list(array.sum("nodes", "techs", "time").items()) == [((), 12.0)]
    assert list(array.select("nodes", "c").sum("techs", "time").items()) == []


def test_the_values_are_not_changed(array: LabeledArray) -> None:
    before = array.values.copy()
    array.sum("time")
    array.max("time")
    array.scale("time", np.array([2.0, 2.0]))
    array.absolute()
    array.take("nodes", ["a"])
    np.testing.assert_array_equal(array.values, before)


# -- reading ----------------------------------------------------------------------------------


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return files.write_netcdf(
        tmp_path / "data.nc",
        {
            "dimensions": {"nodes": 2, "time": 2, "plain": 3},
            "variables": {
                "nodes": (("nodes",), ["a", "b"]),
                "time": (("time",), [0, 1], {"units": files.TIME_UNITS}),
                "values": (("nodes", "time"), [[1.0, NAN], [3.0, 4.0]]),
                "packed": (("nodes",), np.array([2, -1], dtype="i2"),
                           {"_FillValue": np.int16(-1), "scale_factor": 0.5}),
                "flags": (("nodes",), np.array([True, False])),
                "unlabelled": (("plain",), [7, 8, 9]),
                "names": (("nodes",), ["first", ""]),
                "missing": (("nodes",), ["<NA>", "x"], {"_FillValue": "<NA>"}),
                "weights": (("time",), [NAN, 2.0]),
            },
            "groups": {
                "inner": {
                    "dimensions": {"techs": 1},
                    "variables": {
                        "techs": (("techs",), ["pv"]),
                        "flow": (("techs", "nodes"), [[5.0, 6.0]]),
                    },
                }
            },
        },
    )  # fmt: skip


def test_reading_with_labels(path: Path) -> None:
    with open_dataset(path) as dataset:
        array = LabeledArray.read(dataset.variables["values"], dataset)
    assert array.dims == ("nodes", "time")
    assert array.labels == {
        "nodes": ("a", "b"),
        "time": ("2030-01-01T00:00:00", "2030-01-01T01:00:00"),
    }
    np.testing.assert_array_equal(array.values, [[1.0, NAN], [3.0, 4.0]])


def test_labels_of_an_enclosing_group(path: Path) -> None:
    with open_dataset(path) as dataset:
        inner = dataset.groups["inner"]
        array = LabeledArray.read(inner.variables["flow"], inner)
    assert array.labels == {"techs": ("pv",), "nodes": ("a", "b")}


def test_positions_label_a_dimension_without_labels(path: Path) -> None:
    with open_dataset(path) as dataset:
        array = LabeledArray.read(dataset.variables["unlabelled"], dataset)
        assert array.labels == {"plain": ("0", "1", "2")}
        assert LabeledArray.read(dataset.variables["values"]).labels["nodes"] == ("0", "1")
        assert labels_of(dataset, "absent", 2) == ("0", "1")
        assert labels_of(dataset, "nodes", 5) == ("0", "1", "2", "3", "4")
        assert labels_of(None, "nodes", 1) == ("0",)


def test_a_variable_of_the_name_of_a_dimension_is_not_its_labels(path: Path) -> None:
    # "missing" is a variable over the nodes, not the labels of a dimension "missing".
    with open_dataset(path) as dataset:
        assert dataset.variables["missing"].shape == (2,)
        assert labels_of(dataset, "missing", 2) == ("0", "1")


def test_a_label_that_is_missing_is_the_position(path: Path) -> None:
    with open_dataset(path) as dataset:
        dataset.variables["nodes"] = dataset.variables["names"]
        assert labels_of(dataset, "nodes", 2) == ("first", "1")


def test_numbers(path: Path) -> None:
    with open_dataset(path) as dataset:
        np.testing.assert_array_equal(numbers_of(dataset.variables["packed"]), [1.0, NAN])
        assert numbers_of(dataset.variables["flags"]).tolist() == [1.0, 0.0]
        assert numbers_of(dataset.variables["flags"]).dtype == np.float64
        with pytest.raises(ExtractionError, match="/names holds string, not numbers"):
            numbers_of(dataset.variables["names"])
        with pytest.raises(ExtractionError, match="/time holds datetime, not numbers"):
            LabeledArray.read(dataset.variables["time"], dataset)


def test_texts(path: Path) -> None:
    with open_dataset(path) as dataset:
        assert texts_of(dataset.variables["names"]) == ["first", None]
        assert texts_of(dataset.variables["missing"]) == [None, "x"]
        assert texts_of(dataset.variables["unlabelled"]) == ["7", "8", "9"]
        assert texts_of(dataset.variables["time"]) == ["2030-01-01T00:00:00", "2030-01-01T01:00:00"]
        assert texts_of(dataset.variables["flags"]) == ["True", "False"]


@pytest.mark.parametrize("text", ["nan", "NaN", "<NA>", "None", "NaT", ""])
def test_what_the_frameworks_write_for_a_missing_text(tmp_path: Path, text: str) -> None:
    path = files.write_netcdf(
        tmp_path / "data.nc",
        {"dimensions": {"x": 2}, "variables": {"names": (("x",), [text, "value"])}},
    )
    with open_dataset(path) as dataset:
        assert texts_of(dataset.variables["names"]) == [None, "value"]


def test_an_axis_without_a_dimension_is_refused(tmp_path: Path) -> None:
    with open_dataset(files.adopt_net0(tmp_path / "results.h5")) as dataset:
        variable = dataset.variable("/operation/networks/period1/cable/ab/flow")
        with pytest.raises(ExtractionError, match="flow: the axis 0 has no dimension"):
            LabeledArray.read(variable)
        assert numbers_of(variable).tolist() == [4.0, 4.0, 4.0]


def test_weights(path: Path) -> None:
    with open_dataset(path) as dataset:
        assert weights_of(dataset.variables["weights"], 2).tolist() == [1.0, 2.0]
        assert weights_of(dataset.variables["weights"], 3).tolist() == [1.0, 1.0, 1.0]
        assert weights_of(None, 2).tolist() == [1.0, 1.0]


def test_finite() -> None:
    assert finite(np.array([1.0, NAN])).tolist() == [1.0, 0.0]
    assert finite(np.array([1.0, NAN]), nan=7.0).tolist() == [1.0, 7.0]
