"""The results of Calliope 0.6, from files made for the tests."""

from __future__ import annotations

from pathlib import Path

import pytest

import coati
from coati.errors import ExtractionError
from support import files
from support.compare import as_json


def document(path: Path, framework: str = "auto", **options: object) -> dict:
    return as_json(coati.results_document(path, framework, coati.ExtractOptions(**options)))


@pytest.fixture
def solved(tmp_path: Path) -> dict:
    return document(files.calliope06(tmp_path / "model.nc"))


def test_run_is_described(solved: dict) -> None:
    assert solved["framework"] == "calliope"
    assert solved["framework_version"] == "0.6.10"
    assert solved["model_name"] == "Synthetic model"
    assert solved["solver"] == "cbc"
    assert solved["success"] is True
    assert solved["termination_condition"] == "optimal"
    assert solved["details"] == {"mode": "plan"}
    assert solved["metadata"]["framework_family"] == "calliope-v0-6"


def test_the_identifier_may_leave_out_the_leading_zero(tmp_path: Path) -> None:
    found = document(files.calliope06(tmp_path / "model.nc"), "calliope-v6-10")
    assert found["metadata"]["framework_id"] == "calliope-v0-6-10"
    assert found["warnings"] == []


def test_another_version_of_the_family_is_a_remark(tmp_path: Path) -> None:
    found = document(files.calliope06(tmp_path / "model.nc"), "calliope-v0-6-8")
    assert found["framework_version"] == "0.6.10"
    assert found["warnings"] == [
        "the file states Calliope 0.6.10; it is read as such, although Calliope 0.6.8 was named"
    ]


def test_capacities_keep_the_labels_of_the_file(solved: dict) -> None:
    assert solved["capacities"] == {
        "a::pv": 10.0,
        "b::battery": 4.0,
        "b::load": 8.0,
        "a::line:b": 5.0,
        "b::line:a": 5.0,
    }
    assert solved["storage_capacities"] == {"b::battery": 16.0}


def test_generation_counts_each_time_with_its_weight(solved: dict) -> None:
    assert solved["generation"] == {
        "a::pv::power": 26.0,
        "b::battery::power": 4.0,
        "b::line:a::power": 13.0,
        "a::line:b::power": 1.0,
    }


def test_dispatch_leaves_out_demand_and_transmission(solved: dict) -> None:
    assert solved["dispatch"] == {"pv": [6.0, 8.0, 4.0], "battery": [0.0, 1.0, 2.0]}


def test_transmission_reads_the_origin_from_the_name_of_the_technology(solved: dict) -> None:
    # "b::line:a" is what arrives at b from a.
    assert solved["transmission_flow"] == {
        "a::b": {"from": "a", "to": "b", "timeseries": [3.0, 4.0, 1.0]}
    }


def test_demand_is_reported_as_a_magnitude(solved: dict) -> None:
    assert solved["demand_timeseries"] == [5.0, 6.0, 7.0]
    assert solved["demand_by_location"] == {"b": 24.0}


def test_unmet_demand(solved: dict) -> None:
    assert solved["unmet_demand_timeseries"] == [0.0, 0.5, 0.0]
    assert solved["unmet_demand_by_location"] == {"b": 1.0}
    assert solved["total_unmet_demand"] == 1.0


def test_costs_count_the_classes_that_the_objective_lists(solved: dict) -> None:
    # The configuration lists the monetary class alone: the emissions do not count.
    assert solved["costs_by_location"] == {
        "a": {"pv": 100.0, "line:b": 3.0},
        "b": {"battery": 20.0, "line:a": 3.0},
    }
    assert solved["objective"] == 126.0
    assert solved["objective_function_value"] == 127.0


def test_every_class_counts_if_the_configuration_lists_none(tmp_path: Path) -> None:
    path = files.calliope06(tmp_path / "model.nc")
    with files.netCDF4.Dataset(path, "a") as dataset:
        dataset.setncattr("run_config", "solver: cbc\nmode: plan\n")
    assert document(path)["objective"] == 130.0


def test_technologies(solved: dict) -> None:
    metadata = solved["tech_metadata"]
    assert metadata["pv"] == {
        "parent": "supply",
        "carrier_out": "power",
        "display_name": "Solar",
        "color": "#F9D956",
    }
    assert metadata["load"]["parent"] == "demand"
    assert metadata["load"]["carrier_out"] == ""
    assert metadata["battery"]["parent"] == "storage"


def test_the_end_of_a_link_has_the_kind_and_the_labels_of_its_technology(solved: dict) -> None:
    assert solved["tech_metadata"]["line:a"] == {
        "parent": "transmission",
        "carrier_out": "power",
        "display_name": "Line",
        "color": "#8465A9",
    }
    assert solved["tech_parents"]["line:b"] == "transmission"


def test_coordinates_on_the_globe(solved: dict) -> None:
    assert solved["coordinates"] == {"a": [50.0, 10.0], "b": [51.0, 11.0]}


def test_coordinates_in_a_plane_are_left_out(tmp_path: Path) -> None:
    assert "coordinates" not in document(files.calliope06(tmp_path / "model.nc", planar=True))


def test_a_model_without_a_solution(tmp_path: Path) -> None:
    found = document(files.calliope06(tmp_path / "model.nc", condition="infeasible"))
    assert found["success"] is False
    assert found["termination_condition"] == "infeasible"


def test_a_run_whose_end_the_file_does_not_state(tmp_path: Path) -> None:
    found = document(files.calliope06(tmp_path / "model.nc", condition=""))
    assert found["termination_condition"] == "unknown"
    assert found["success"] is False
    assert found["capacities"]["a::pv"] == 10.0


def test_a_model_that_has_not_been_solved(tmp_path: Path) -> None:
    solution = ("energy_cap", "storage_cap", "carrier_prod", "carrier_con", "cost", "unmet_demand")
    path = files.calliope06(tmp_path / "model.nc", condition="", without=solution)
    found = document(path)
    assert found["success"] is False
    assert found["termination_condition"] == "not_solved"
    assert found["objective"] is None
    assert found["capacities"] == {}
    assert found["generation"] == {}
    assert found["dispatch"] == {}
    assert found["demand_timeseries"] == []
    assert found["transmission_flow"] == {}
    assert found["costs_by_location"] == {}
    assert found["timestamps"] == files.TIMESTAMPS
    assert found["tech_parents"]["pv"] == "supply"
    assert found["warnings"] == ["the file holds no results: the model has not been solved"]


def test_a_file_without_what_describes_the_technologies(tmp_path: Path) -> None:
    described = ("inheritance", "names", "colors", "loc_coordinates", "timestep_weights")
    found = document(files.calliope06(tmp_path / "model.nc", without=described))
    assert found["tech_metadata"] == {}
    assert "coordinates" not in found
    assert "weights" not in found
    # What a technology is follows from its name: a link names the other end, a demand itself.
    assert found["transmission_flow"]["a::b"]["timeseries"] == [3.0, 4.0, 1.0]
    assert found["dispatch"] == {"pv": [6.0, 8.0, 4.0], "battery": [0.0, 1.0, 2.0]}
    assert found["generation"]["a::pv::power"] == 18.0


def test_a_demand_is_known_by_its_name_if_nothing_else_tells(tmp_path: Path) -> None:
    path = files.calliope06(tmp_path / "model.nc", without=("inheritance",))
    with files.netCDF4.Dataset(path, "a") as dataset:
        labels = dataset.variables["loc_tech_carriers_con"]
        labels[0] = "b::demand_power::power"
    found = document(path)
    assert found["demand_timeseries"] == [5.0, 6.0, 7.0]
    assert found["demand_by_location"] == {"b": 24.0}


def test_labels_are_not_shown_if_not_wanted(tmp_path: Path) -> None:
    found = document(files.calliope06(tmp_path / "model.nc"), labels=False)
    assert found["tech_metadata"]["pv"] == {"parent": "supply", "carrier_out": "power"}
    assert found["tech_metadata"]["line:a"] == {"parent": "transmission", "carrier_out": "power"}


def test_a_weight_that_is_no_number_counts_as_zero(tmp_path: Path) -> None:
    run = "objective_options:\n  cost_class:\n    monetary: all\n    emissions: 0.5\n"
    found = document(files.calliope06(tmp_path / "model.nc", run=run))
    assert found["objective"] == 0.5 * 4
    assert found["solver"] is None
    assert "details" not in found


def test_the_primary_carrier_is_the_one_a_technology_puts_out(tmp_path: Path) -> None:
    path = files.calliope06(tmp_path / "model.nc")
    with files.netCDF4.Dataset(path, "a") as dataset:
        dataset.createDimension("loc_techs_conversion_plus", 2)
        lookup = dataset.createVariable(
            "lookup_primary_loc_tech_carriers_out", str, ("loc_techs_conversion_plus",)
        )
        lookup[0] = "b::battery::heat"
        lookup[1] = ""
    found = document(path)
    assert found["tech_metadata"]["battery"]["carrier_out"] == "heat"
    assert found["tech_metadata"]["pv"]["carrier_out"] == "power"


def test_spores_report_the_first_and_list_all(tmp_path: Path) -> None:
    found = document(files.calliope06(tmp_path / "model.nc", spores=3))
    assert found["objective"] == 126.0
    assert found["dispatch"]["pv"] == [6.0, 8.0, 4.0]
    assert found["capacities"]["a::pv"] == 10.0
    assert found["details"]["mode"] == "spores"
    spores = found["details"]["spores"]
    assert [entry["spore"] for entry in spores] == ["0", "1", "2"]
    assert [entry["cost"] for entry in spores] == [126.0, 252.0, 378.0]
    assert [entry["capacities"]["a::pv"] for entry in spores] == [10.0, 20.0, 30.0]
    assert [entry["generation"]["a::pv::power"] for entry in spores] == [26.0, 52.0, 78.0]
    assert found["warnings"] == [
        (
            "the file holds 3 solutions of the SPORES mode; the document reports the first,"
            " details.spores lists the cost, the capacities and the generation of each"
        )
    ]


def test_the_first_of_the_spores_is_what_the_document_reports(tmp_path: Path) -> None:
    found = document(files.calliope06(tmp_path / "model.nc", spores=2))
    first = found["details"]["spores"][0]
    assert first["cost"] == found["objective"]
    assert first["capacities"] == found["capacities"]
    assert first["generation"] == found["generation"]
    plain = document(files.calliope06(tmp_path / "plain.nc"))
    for key in ("capacities", "generation", "dispatch", "costs_by_location", "objective"):
        assert found[key] == plain[key]


def test_a_variable_over_several_sets_is_refused(tmp_path: Path) -> None:
    path = files.calliope06(tmp_path / "model.nc", without=("energy_cap",))
    with files.netCDF4.Dataset(path, "a") as dataset:
        dataset.createVariable("energy_cap", "f8", ("locs", "techs"))
    with pytest.raises(ExtractionError) as caught:
        coati.results_document(path)
    assert str(caught.value) == (
        "/energy_cap has the dimensions locs, techs;"
        " expected is one set of locations and technologies"
    )


def test_production_without_times_is_refused(tmp_path: Path) -> None:
    path = files.calliope06(tmp_path / "model.nc", without=("carrier_prod",))
    with files.netCDF4.Dataset(path, "a") as dataset:
        dataset.createVariable("carrier_prod", "f8", ("loc_tech_carriers_prod",))
    with pytest.raises(ExtractionError, match="/carrier_prod has no dimension timesteps"):
        coati.results_document(path)


def test_consumption_without_times_is_refused(tmp_path: Path) -> None:
    path = files.calliope06(tmp_path / "model.nc", without=("carrier_con",))
    with files.netCDF4.Dataset(path, "a") as dataset:
        dataset.createVariable("carrier_con", "f8", ("loc_tech_carriers_con",))
    with pytest.raises(ExtractionError, match="/carrier_con has no dimension timesteps"):
        coati.results_document(path)


def test_unmet_demand_without_times_is_left_out(tmp_path: Path) -> None:
    path = files.calliope06(tmp_path / "model.nc", without=("unmet_demand",))
    with files.netCDF4.Dataset(path, "a") as dataset:
        dataset.createVariable("unmet_demand", "f8", ("loc_carriers",))
    assert "unmet_demand_timeseries" not in document(path)
