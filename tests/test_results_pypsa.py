"""The results of PyPSA, from files made for the tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import coati
from coati.errors import ExtractionError
from support import files
from support.compare import as_json


def document(path: Path, framework: str = "auto", **options: object) -> dict:
    return as_json(coati.results_document(path, framework, coati.ExtractOptions(**options)))


@pytest.fixture(params=["netcdf", "hdf5"])
def solved(request: pytest.FixtureRequest, tmp_path: Path) -> dict:
    """The document of the network, read from each of the two formats."""
    if request.param == "netcdf":
        return document(files.pypsa_netcdf(tmp_path / "network.nc"))
    return document(files.pypsa_hdf5(tmp_path / "network.h5"))


def test_run_is_described(solved: dict) -> None:
    assert solved["framework"] == "pypsa"
    assert solved["framework_version"] == "1.2.4"
    assert solved["model_name"] == "synthetic"
    assert solved["solver"] is None
    assert solved["success"] is True
    assert solved["termination_condition"] == "optimal"
    assert solved["metadata"]["framework_family"] == "pypsa-v1"
    assert solved["warnings"] == []


def test_the_objective_is_the_cost_of_the_system(solved: dict) -> None:
    # The sun costs 50, the gas 40 and 130, the line 20.
    assert solved["objective"] == 240.0
    total = sum(sum(costs.values()) for costs in solved["costs_by_location"].values())
    assert solved["objective"] == total


def test_the_objective_of_pypsa_can_be_reconciled(solved: dict) -> None:
    assert solved["objective_function_value"] == files.PYPSA_OBJECTIVE
    assert solved["details"] == {
        "objective_constant": files.PYPSA_CONSTANT,
        "capital_cost_of_given_capacities": 2.0 * 20,
        "cost_of_unmet_demand": 1000.0 * 0.5 * 2,
    }
    details = solved["details"]
    assert solved["objective_function_value"] + details["objective_constant"] == (
        solved["objective"]
        - details["capital_cost_of_given_capacities"]
        + details["cost_of_unmet_demand"]
    )


def test_timestamps_and_weights(solved: dict) -> None:
    assert solved["timestamps"] == files.TIMESTAMPS
    assert solved["weights"] == files.WEIGHTS


def test_locations_come_from_the_buses_and_technologies_from_the_names(solved: dict) -> None:
    # "pv@a" and "b::gas" state their location, "line" and "battery" do not.
    # The line joins two locations: its capacity is listed at both.
    assert solved["capacities"] == {
        "a::pv": 10.0,
        "b::gas": 20.0,
        "b::battery": 4.0,
        "a::line": 5.0,
        "b::line": 5.0,
    }


def test_the_capacity_of_a_store_is_its_power_times_its_hours(solved: dict) -> None:
    assert solved["storage_capacities"] == {"b::battery": 16.0}


def test_generation_counts_each_snapshot_with_its_weight(solved: dict) -> None:
    assert solved["generation"] == {
        "a::pv::power": 6 + 2 * 8 + 4,
        "b::gas::power": 1 + 2 * 0 + 2,
        "b::battery::power": 0 + 2 * 1 + 0,
        "b::line::power": 2 + 2 * 3 + 0,
        "a::line::power": 0 + 2 * 0 + 2,
    }


def test_dispatch_is_what_is_put_out(solved: dict) -> None:
    # The battery charges in the last hour: that is no output.
    assert solved["dispatch"] == {
        "pv": [6.0, 8.0, 4.0],
        "gas": [1.0, 0.0, 2.0],
        "battery": [0.0, 1.0, 0.0],
    }


def test_a_generator_that_sheds_load_is_unmet_demand(solved: dict) -> None:
    assert "shed" not in solved["dispatch"]
    assert "b::shed" not in solved["capacities"]
    assert solved["unmet_demand_timeseries"] == [0.0, 0.5, 0.0]
    assert solved["unmet_demand_by_location"] == {"b": 1.0}
    assert solved["total_unmet_demand"] == 1.0


def test_transmission_is_what_arrives(solved: dict) -> None:
    # Half of what enters the line is lost: the flow is counted where it arrives.
    assert solved["transmission_flow"] == {
        "a::b": {"from": "a", "to": "b", "timeseries": [2.0, 3.0, -2.0]}
    }


def test_demand(solved: dict) -> None:
    assert solved["demand_timeseries"] == [5.0, 6.0, 7.0]
    assert solved["demand_by_location"] == {"b": 24.0}


def test_costs_follow_the_statistics_of_pypsa(solved: dict) -> None:
    # pv: 5 per unit of capacity; gas: 2 per unit of capacity and a price that changes with
    # time, 30, 40 and 50; line: 4 per unit of capacity, shared by its two ends.
    assert solved["costs_by_location"] == {
        "a": {"pv": 50.0, "line": 10.0},
        "b": {"gas": 2 * 20 + 30 * 1 + 40 * 0 * 2 + 50 * 2, "battery": 0.0, "line": 10.0},
    }
    assert solved["costs_by_tech"] == {"pv": 50.0, "gas": 170.0, "line": 20.0}


def test_technologies(solved: dict) -> None:
    assert solved["tech_metadata"] == {
        "pv": {"parent": "supply", "carrier_out": "power"},
        "gas": {"parent": "supply", "carrier_out": "power"},
        "battery": {"parent": "storage", "carrier_out": "power"},
        "load": {"parent": "demand", "carrier_out": ""},
        "line": {"parent": "transmission", "carrier_out": "power"},
    }


def test_coordinates_are_latitude_then_longitude(solved: dict) -> None:
    assert solved["coordinates"] == {"a": [50.0, 10.0], "b": [51.0, 11.0]}


def test_both_formats_give_the_same_document(tmp_path: Path) -> None:
    first = document(files.pypsa_netcdf(tmp_path / "network.nc"))
    second = document(files.pypsa_hdf5(tmp_path / "network.h5"))
    for found in (first, second):
        del found["metadata"]["source"]
    assert first == second


def test_a_network_that_has_not_been_optimised(tmp_path: Path) -> None:
    found = document(files.pypsa_netcdf(tmp_path / "network.nc", solved=False))
    assert found["success"] is False
    assert found["termination_condition"] == "not_solved"
    assert found["objective"] is None
    assert "objective_function_value" not in found
    assert found["dispatch"] == {}
    assert found["capacities"] == {
        "a::pv": 0.0,
        "b::gas": 0.0,
        "b::battery": 0.0,
        "a::line": 0.0,
        "b::line": 0.0,
    }
    assert found["costs_by_location"] == {}
    assert found["costs_by_tech"] == {}
    assert "details" not in found
    assert found["warnings"] == [
        (
            "the network has no objective: it has not been optimised,"
            " and the capacities are those given, not decided"
        )
    ]


def test_a_network_that_has_not_been_optimised_reports_what_is_given(tmp_path: Path) -> None:
    path = _network(
        tmp_path,
        objective=None,
        generators_i=(("generators_i",), ["wind"]),
        generators_bus=(("generators_i",), ["hub"]),
        generators_p_nom=(("generators_i",), [3.0]),
        generators_p_nom_opt=(("generators_i",), [9.0]),
        generators_capital_cost=(("generators_i",), [2.0]),
    )
    found = document(path)
    assert found["capacities"] == {"hub::wind": 3.0}
    assert found["costs_by_location"] == {}


def test_an_older_version_names_the_objective_differently(tmp_path: Path) -> None:
    found = document(files.pypsa_netcdf(tmp_path / "network.nc", version="0.25.2"))
    assert found["objective"] == 240.0
    assert found["objective_function_value"] == files.PYPSA_OBJECTIVE
    assert found["details"]["objective_constant"] == files.PYPSA_CONSTANT
    assert found["metadata"]["framework_family"] == "pypsa-v0"
    assert found["warnings"] == []


def test_instants_written_as_text_are_normalised(tmp_path: Path) -> None:
    found = document(files.pypsa_netcdf(tmp_path / "network.nc", snapshots="text"))
    assert found["timestamps"] == files.TIMESTAMPS


def test_snapshots_that_are_numbers_stay_numbers(tmp_path: Path) -> None:
    found = document(files.pypsa_netcdf(tmp_path / "network.nc", snapshots="number"))
    assert found["timestamps"] == [0, 1, 2]


def test_snapshots_that_are_numbers_can_be_given_times(tmp_path: Path) -> None:
    path = files.pypsa_netcdf(tmp_path / "network.nc", snapshots="number")
    found = document(path, time_start="2030-01-01T00:00", time_step="1h")
    assert found["timestamps"] == files.TIMESTAMPS


def test_the_times_of_the_file_win_over_those_of_the_caller(tmp_path: Path) -> None:
    path = files.pypsa_netcdf(tmp_path / "network.nc")
    found = document(path, time_start="1999-01-01T00:00", time_step="1d")
    assert found["timestamps"] == files.TIMESTAMPS


def _network(tmp_path: Path, objective: float | None = 0.0, **changes: object) -> Path:
    """Write a network of one bus with the components that ``changes`` describe.

    Args:
        tmp_path: The directory of the file.
        objective: The objective that the network states; none if it has not been optimised.
        **changes: The variables of the file.
    """
    attributes: dict[str, object] = {"network_pypsa_version": "1.2.4"}
    if objective is not None:
        attributes["network__objective"] = objective
    variables = {
        "snapshots": (("snapshots",), np.arange(2)),
        "buses_i": (("buses_i",), ["hub"]),
        **changes,
    }
    dimensions = {
        dim: size
        for dims, values in variables.values()
        for dim, size in zip(dims, np.shape(values), strict=True)
    }
    return files.write_netcdf(
        tmp_path / "network.nc",
        {"attributes": attributes, "dimensions": dimensions, "variables": variables},
    )


def test_a_bus_without_a_carrier_carries_alternating_current(tmp_path: Path) -> None:
    path = _network(
        tmp_path,
        generators_i=(("generators_i",), ["wind"]),
        generators_bus=(("generators_i",), ["hub"]),
        generators_p_nom_opt=(("generators_i",), [3.0]),
    )
    found = document(path)
    assert found["capacities"] == {"hub::wind": 3.0}
    assert found["generation"] == {"hub::wind::AC": 0.0}
    assert found["timestamps"] == [0, 1]
    assert "weights" not in found


def test_a_link_between_carriers_is_a_conversion(tmp_path: Path) -> None:
    path = _network(
        tmp_path,
        objective=1.0 * 15,
        buses_i=(("buses_i",), ["hub::power", "hub::heat", "hub::steam"]),
        links_i=(("links_i",), ["chp"]),
        links_bus0=(("links_i",), ["hub::power"]),
        links_bus1=(("links_i",), ["hub::heat"]),
        links_bus2=(("links_i",), ["hub::steam"]),
        links_p_nom_opt=(("links_i",), [10.0]),
        links_efficiency=(("links_i",), [0.4]),
        links_capital_cost=(("links_i",), [2.0]),
        links_marginal_cost=(("links_i",), [1.0]),
        links_t_p0_i=(("links_t_p0_i",), ["chp"]),
        links_t_p0=(("snapshots", "links_t_p0_i"), [[10.0], [5.0]]),
        links_t_p1_i=(("links_t_p1_i",), ["chp"]),
        links_t_p1=(("snapshots", "links_t_p1_i"), [[-4.0], [-2.0]]),
        links_t_p2_i=(("links_t_p2_i",), ["chp"]),
        links_t_p2=(("snapshots", "links_t_p2_i"), [[-3.0], [-1.5]]),
    )
    found = document(path)
    assert found["tech_metadata"]["chp"] == {"parent": "conversion", "carrier_out": "heat"}
    assert found["capacities"] == {"hub::chp": 4.0}
    assert found["generation"] == {"hub::chp::heat": 6.0, "hub::chp::steam": 4.5}
    assert found["dispatch"] == {"chp": [7.0, 3.5]}
    assert found["costs_by_location"] == {"hub": {"chp": 2.0 * 10 + 1.0 * 15}}
    assert found["transmission_flow"] == {}
    assert found["warnings"] == []


def test_lines_are_transmission(tmp_path: Path) -> None:
    path = _network(
        tmp_path,
        buses_i=(("buses_i",), ["east", "west"]),
        lines_i=(("lines_i",), ["ac"]),
        lines_bus0=(("lines_i",), ["west"]),
        lines_bus1=(("lines_i",), ["east"]),
        lines_s_nom_opt=(("lines_i",), [50.0]),
        lines_capital_cost=(("lines_i",), [3.0]),
        lines_t_p0_i=(("lines_t_p0_i",), ["ac"]),
        lines_t_p0=(("snapshots", "lines_t_p0_i"), [[20.0], [-10.0]]),
        lines_t_p1_i=(("lines_t_p1_i",), ["ac"]),
        lines_t_p1=(("snapshots", "lines_t_p1_i"), [[-20.0], [10.0]]),
    )
    found = document(path)
    assert found["capacities"] == {"west::ac": 50.0, "east::ac": 50.0}
    assert found["costs_by_location"] == {"west": {"ac": 75.0}, "east": {"ac": 75.0}}
    assert found["objective"] == 150.0
    assert found["details"] == {"capital_cost_of_given_capacities": 150.0}
    # The pair is named in the order of the names: east before west.
    assert found["transmission_flow"] == {
        "east::west": {"from": "east", "to": "west", "timeseries": [-20.0, 10.0]}
    }
    assert found["warnings"] == []


def test_a_connection_within_a_location_is_listed_once(tmp_path: Path) -> None:
    path = _network(
        tmp_path,
        objective=150.0,
        buses_i=(("buses_i",), ["hub::high", "hub::low"]),
        transformers_i=(("transformers_i",), ["station"]),
        transformers_bus0=(("transformers_i",), ["hub::high"]),
        transformers_bus1=(("transformers_i",), ["hub::low"]),
        transformers_s_nom_opt=(("transformers_i",), [50.0]),
        transformers_s_nom_extendable=(("transformers_i",), np.array([True])),
        transformers_capital_cost=(("transformers_i",), [3.0]),
    )
    found = document(path)
    assert found["capacities"] == {"hub::station": 50.0}
    assert found["costs_by_location"] == {"hub": {"station": 150.0}}
    assert found["tech_metadata"] == {"station": {"parent": "transmission", "carrier_out": "high"}}
    assert found["transmission_flow"] == {}
    assert found["warnings"] == []


def test_an_objective_that_the_costs_do_not_explain(tmp_path: Path) -> None:
    path = _network(
        tmp_path,
        objective=500.0,
        generators_i=(("generators_i",), ["wind"]),
        generators_bus=(("generators_i",), ["hub"]),
        generators_p_nom_opt=(("generators_i",), [3.0]),
        generators_p_nom_extendable=(("generators_i",), np.array([True])),
        generators_capital_cost=(("generators_i",), [100.0]),
    )
    found = document(path)
    assert found["objective"] == 300.0
    assert found["objective_function_value"] == 500.0
    assert found["warnings"] == [
        (
            "the objective of the network and its constant add up to 500, the costs that the"
            " document counts towards them to 300; the network may have been optimised with"
            " an objective of its own, or in several steps"
        )
    ]


def test_an_objective_may_differ_by_what_the_solver_tolerates(tmp_path: Path) -> None:
    path = _network(
        tmp_path,
        objective=300.0 * (1 + 5e-5),
        generators_i=(("generators_i",), ["wind"]),
        generators_bus=(("generators_i",), ["hub"]),
        generators_p_nom_opt=(("generators_i",), [3.0]),
        generators_p_nom_extendable=(("generators_i",), np.array([True])),
        generators_capital_cost=(("generators_i",), [100.0]),
    )
    assert document(path)["warnings"] == []


def test_costs_that_the_document_does_not_count_are_named(tmp_path: Path) -> None:
    path = _network(
        tmp_path,
        objective=500.0,
        generators_i=(("generators_i",), ["coal", "wind"]),
        generators_bus=(("generators_i",), ["hub", "hub"]),
        generators_p_nom_opt=(("generators_i",), [3.0, 1.0]),
        generators_start_up_cost=(("generators_i",), [200.0, 0.0]),
        generators_shut_down_cost=(("generators_i",), [0.0, 0.0]),
        storage_units_i=(("storage_units_i",), ["dam"]),
        storage_units_bus=(("storage_units_i",), ["hub"]),
        storage_units_t_spill_cost_i=(("storage_units_t_spill_cost_i",), ["dam"]),
        storage_units_t_spill_cost=(("snapshots", "storage_units_t_spill_cost_i"), [[0.0], [1.5]]),
    )
    assert document(path)["warnings"] == [
        (
            "the network states costs that the document does not count:"
            " start_up_cost of the generators, spill_cost of the storage_units"
        )
    ]


def test_a_store_has_a_capacity_for_energy_alone(tmp_path: Path) -> None:
    path = _network(
        tmp_path,
        stores_i=(("stores_i",), ["tank"]),
        stores_bus=(("stores_i",), ["hub"]),
        stores_e_nom_opt=(("stores_i",), [40.0]),
        stores_capital_cost=(("stores_i",), [0.5]),
        stores_t_p_i=(("stores_t_p_i",), ["tank"]),
        stores_t_p=(("snapshots", "stores_t_p_i"), [[3.0], [-3.0]]),
    )
    found = document(path)
    assert found["capacities"] == {}
    assert found["storage_capacities"] == {"hub::tank": 40.0}
    assert found["dispatch"] == {"tank": [3.0, 0.0]}
    assert found["costs_by_location"] == {"hub": {"tank": 20.0}}
    assert found["warnings"] == []


def test_a_load_without_results_reports_what_is_set(tmp_path: Path) -> None:
    path = _network(
        tmp_path,
        loads_i=(("loads_i",), ["town", "village"]),
        loads_bus=(("loads_i",), ["hub", "hub"]),
        loads_p_set=(("loads_i",), [7.0, 0.0]),
        loads_t_p_set_i=(("loads_t_p_set_i",), ["village"]),
        loads_t_p_set=(("snapshots", "loads_t_p_set_i"), [[1.0], [2.0]]),
    )
    found = document(path)
    assert found["demand_timeseries"] == [8.0, 9.0]
    assert found["demand_by_location"] == {"hub": 17.0}


def test_coordinates_in_another_reference_system_are_left_out(tmp_path: Path) -> None:
    path = files.pypsa_netcdf(tmp_path / "network.nc")
    with files.netCDF4.Dataset(path, "a") as dataset:
        dataset.setncattr("network_srid", np.array([25832]))
    assert "coordinates" not in document(path)


def test_scenarios_are_reported_as_their_expectation(tmp_path: Path) -> None:
    path = files.write_netcdf(
        tmp_path / "network.nc",
        {
            "attributes": {"network_pypsa_version": "1.2.4", "network__objective": 54.0},
            "dimensions": {"snapshots": 2, "scenario": 2, "generators_i": 1, "buses_i": 1,
                           "generators_t_p_i": 1},
            "variables": {
                "snapshots": (("snapshots",), np.arange(2)),
                "scenario": (("scenario",), ["dear", "cheap"]),
                "scenario_weight": (("scenario",), [0.25, 0.75]),
                "buses_i": (("buses_i",), ["hub"]),
                "generators_i": (("generators_i",), ["gas"]),
                "generators_bus": (("scenario", "generators_i"), [["hub"], ["hub"]]),
                "generators_p_nom_opt": (("scenario", "generators_i"), [[10.0], [10.0]]),
                "generators_marginal_cost": (("scenario", "generators_i"), [[8.0], [4.0]]),
                "generators_t_p_i": (("generators_t_p_i",), ["gas"]),
                "generators_t_p": (
                    ("snapshots", "scenario", "generators_t_p_i"),
                    [[[2.0], [6.0]], [[4.0], [8.0]]],
                ),
            },
        },
    )  # fmt: skip
    found = document(path)
    assert found["scenarios"] == {"dear": 0.25, "cheap": 0.75}
    assert found["capacities"] == {"hub::gas": 10.0}
    assert found["dispatch"] == {"gas": [0.25 * 2 + 0.75 * 6, 0.25 * 4 + 0.75 * 8]}
    assert found["generation"] == {"hub::gas::AC": 0.25 * 6 + 0.75 * 14}
    assert found["costs_by_tech"] == {"gas": 0.25 * 8 * 6 + 0.75 * 4 * 14}
    assert found["objective"] == 54.0
    assert found["warnings"] == [
        "the network has 2 scenarios; the document reports the expectation"
    ]


def test_periods_of_investment_are_listed(tmp_path: Path) -> None:
    path = _network(
        tmp_path,
        snapshots_period=(("snapshots",), np.array([2030, 2040], dtype="i4")),
        snapshots_timestep=(("snapshots",), ["2030-01-01 00:00:00", "2040-01-01 00:00:00"]),
    )
    found = document(path)
    assert found["periods"] == [2030, 2040]
    assert found["timestamps"] == ["2030-01-01T00:00:00", "2040-01-01T00:00:00"]


def test_the_objective_of_several_periods_is_not_reconciled(tmp_path: Path) -> None:
    # The objective weighs the periods, the costs of the document do not.
    path = _network(
        tmp_path,
        objective=500.0,
        snapshots_period=(("snapshots",), np.array([2030, 2040], dtype="i4")),
        snapshots_timestep=(("snapshots",), ["2030-01-01 00:00:00", "2040-01-01 00:00:00"]),
        generators_i=(("generators_i",), ["wind"]),
        generators_bus=(("generators_i",), ["hub"]),
        generators_p_nom_opt=(("generators_i",), [3.0]),
        generators_p_nom_extendable=(("generators_i",), np.array([True])),
        generators_capital_cost=(("generators_i",), [100.0]),
    )
    found = document(path)
    assert found["objective"] == 300.0
    assert found["warnings"] == []


def test_a_file_without_tables_is_refused(tmp_path: Path) -> None:
    path = files.write_netcdf(
        tmp_path / "network.nc", {"attributes": {"network_pypsa_version": "1.2.4"}}
    )
    with pytest.raises(ExtractionError, match="holds no tables of a network"):
        coati.results_document(path)
