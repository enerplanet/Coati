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
    details = solved["details"]
    assert {key: details[key] for key in details if key != "global_constraints"} == {
        "objective_constant": files.PYPSA_CONSTANT,
        "capital_cost_of_given_capacities": 2.0 * 20,
        "cost_of_unmet_demand": 1000.0 * 0.5 * 2,
    }
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


def test_the_costs_are_told_fixed_from_variable(solved: dict) -> None:
    # The capital cost is fixed, whether the capacity was decided or given; what the operation
    # costs is variable. Every entry of the costs has its two parts.
    assert solved["fixed_costs_by_location"] == {
        "a": {"pv": 50.0, "line": 10.0},
        "b": {"gas": 40.0, "battery": 0.0, "line": 10.0},
    }
    assert solved["variable_costs_by_location"] == {
        "a": {"pv": 0.0, "line": 0.0},
        "b": {"gas": 130.0, "battery": 0.0, "line": 0.0},
    }


def test_storage_levels_are_the_state_of_charge(solved: dict) -> None:
    assert solved["storage_levels"] == {"b::battery": [2.0, 1.0, 3.0]}


def test_prices_are_the_marginal_prices_of_the_buses(solved: dict) -> None:
    assert solved["prices"] == {"a::power": [30.0, 40.0, 50.0], "b::power": [30.0, 40.0, 50.0]}


def test_emissions_follow_the_carriers(solved: dict) -> None:
    # The gas burns 1, 0 and 2 at 0.2 a unit; the snapshots weigh 1, 2 and 1. The sun emits
    # nothing, and the generator that sheds load is no technology.
    assert solved["emissions_by_location"] == {"a::pv": 0.0, "b::gas": pytest.approx(0.6)}
    assert solved["total_emissions"] == pytest.approx(0.6)


def test_curtailment_is_what_the_resource_allowed_but_was_not_put_out(solved: dict) -> None:
    # The sun allowed 8, 10 and 5 of the 10 that were built; 6, 8 and 4 were put out.
    assert solved["curtailment"] == {"a::pv": 2 + 2 * 2 + 1}


def test_global_constraints_are_reported_as_stated(solved: dict) -> None:
    assert solved["details"]["global_constraints"] == {
        "co2_cap": {
            "type": "primary_energy",
            "carrier_attribute": "co2_emissions",
            "sense": "<=",
            "constant": 100.0,
            "mu": 0.0,
        }
    }


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
    for key in (
        "storage_levels",
        "prices",
        "curtailment",
        "emissions_by_location",
        "fixed_costs_by_location",
        "variable_costs_by_location",
    ):
        assert key not in found
    assert found["capacities"] == {
        "a::pv": 0.0,
        "b::gas": 0.0,
        "b::battery": 0.0,
        "a::line": 0.0,
        "b::line": 0.0,
    }
    assert found["costs_by_location"] == {}
    assert found["costs_by_tech"] == {}
    # The limit on emissions is part of the model, decided or not; nothing else is to report.
    assert list(found["details"]) == ["global_constraints"]
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


def test_the_name_of_a_bus_states_its_carrier(tmp_path: Path) -> None:
    # The attribute says AC, as PyPSA has it for every bus of a power flow; the name says more.
    # A third part of the name tells the buses of a location and a carrier apart.
    path = _network(
        tmp_path,
        buses_i=(("buses_i",), ["hub::power", "hub::power::tank", "plain"]),
        buses_carrier=(("buses_i",), ["AC", "AC", "AC"]),
        generators_i=(("generators_i",), ["wind", "pump", "diesel"]),
        generators_bus=(("generators_i",), ["hub::power", "hub::power::tank", "plain"]),
        generators_p_nom_opt=(("generators_i",), [3.0, 1.0, 2.0]),
    )
    found = document(path)
    assert found["generation"] == {
        "hub::wind::power": 0.0,
        "hub::pump::power": 0.0,
        "plain::diesel::AC": 0.0,
    }


def test_the_noise_of_a_solver_is_no_dispatch(tmp_path: Path) -> None:
    path = _network(
        tmp_path,
        generators_i=(("generators_i",), ["idle", "busy"]),
        generators_bus=(("generators_i",), ["hub", "hub"]),
        generators_p_nom_opt=(("generators_i",), [3.0, 3.0]),
        generators_t_p_i=(("generators_t_p_i",), ["idle", "busy"]),
        generators_t_p=(("snapshots", "generators_t_p_i"), [[1e-9, 1e-6], [-1e-9, 0.0]]),
    )
    found = document(path)
    assert found["dispatch"] == {"busy": [1e-6, 0.0]}
    assert found["generation"] == {"hub::idle::AC": 0.0, "hub::busy::AC": 1e-6}


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


def test_a_cost_whose_series_the_file_lacks_is_nothing(tmp_path: Path) -> None:
    # PyPSA writes a series only where a value differs from the default: no start-up, no spill.
    path = _network(
        tmp_path,
        objective=0.0,
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
    found = document(path)
    assert found["costs_by_location"] == {"hub": {"coal": 0.0, "wind": 0.0, "dam": 0.0}}
    assert found["objective"] == 0.0
    assert found["warnings"] == []


def committable(tmp_path: Path, *, is_committable: bool = True, **changes: object) -> Path:
    """A committable generator: on in the second hour, with the costs of commitment."""
    return _network(
        tmp_path,
        snapshots=(("snapshots",), np.arange(3)),
        snapshots_objective=(("snapshots",), [1.0, 2.0, 1.0]),
        generators_i=(("generators_i",), ["coal"]),
        generators_bus=(("generators_i",), ["hub"]),
        generators_p_nom=(("generators_i",), [100.0]),
        generators_p_nom_opt=(("generators_i",), [100.0]),
        generators_committable=(("generators_i",), np.array([is_committable])),
        generators_marginal_cost=(("generators_i",), [10.0]),
        generators_stand_by_cost=(("generators_i",), [5.0]),
        generators_start_up_cost=(("generators_i",), [300.0]),
        generators_shut_down_cost=(("generators_i",), [70.0]),
        generators_t_p_i=(("generators_t_p_i",), ["coal"]),
        generators_t_p=(("snapshots", "generators_t_p_i"), [[0.0], [40.0], [0.0]]),
        generators_t_status_i=(("generators_t_status_i",), ["coal"]),
        generators_t_status=(("snapshots", "generators_t_status_i"), [[0.0], [1.0], [0.0]]),
        generators_t_start_up_i=(("generators_t_start_up_i",), ["coal"]),
        generators_t_start_up=(("snapshots", "generators_t_start_up_i"), [[0.0], [1.0], [0.0]]),
        generators_t_shut_down_i=(("generators_t_shut_down_i",), ["coal"]),
        generators_t_shut_down=(("snapshots", "generators_t_shut_down_i"), [[0.0], [0.0], [1.0]]),
        **changes,
    )


def test_the_costs_of_commitment_are_counted(tmp_path: Path) -> None:
    # Running: 10 * 40 * 2. Standing by: 5 * 1 * 2, for as long as the unit is on. Starting up
    # and shutting down: once each, whatever the hour weighs.
    path = committable(tmp_path, objective=800.0 + 10.0 + 300.0 + 70.0)
    found = document(path)
    assert found["costs_by_location"] == {"hub": {"coal": 1180.0}}
    assert found["objective"] == 1180.0
    assert found["objective_function_value"] == 1180.0
    assert "details" not in found
    assert found["warnings"] == []


def test_a_unit_whose_status_the_file_lacks_was_on_all_the_time(tmp_path: Path) -> None:
    # The default of the status is on, and PyPSA writes a series only where a value differs
    # from the default: a committable unit that was never off stands by at every snapshot.
    path = committable(tmp_path, objective=800.0 + 5.0 * 4 + 300.0 + 70.0)
    with files.netCDF4.Dataset(path, "a") as dataset:
        dataset.renameVariable("generators_t_status", "generators_t_status_gone")
    found = document(path)
    assert found["costs_by_location"] == {"hub": {"coal": 800.0 + 20.0 + 300.0 + 70.0}}
    assert found["warnings"] == []


def test_a_unit_that_is_not_committable_does_not_stand_by(tmp_path: Path) -> None:
    path = committable(tmp_path, is_committable=False, objective=800.0 + 300.0 + 70.0)
    with files.netCDF4.Dataset(path, "a") as dataset:
        dataset.renameVariable("generators_t_status", "generators_t_status_gone")
    found = document(path)
    assert found["costs_by_location"] == {"hub": {"coal": 1170.0}}
    assert found["warnings"] == []


def test_a_carrier_named_unmet_is_demand_that_is_not_met(tmp_path: Path) -> None:
    path = _network(
        tmp_path,
        objective=500.0 * 3,
        generators_i=(("generators_i",), ["hub::electricity::unmet"]),
        generators_bus=(("generators_i",), ["hub"]),
        generators_carrier=(("generators_i",), ["unmet"]),
        generators_p_nom_opt=(("generators_i",), [3.0]),
        generators_p_nom_extendable=(("generators_i",), np.array([True])),
        generators_marginal_cost=(("generators_i",), [500.0]),
        generators_t_p_i=(("generators_t_p_i",), ["hub::electricity::unmet"]),
        generators_t_p=(("snapshots", "generators_t_p_i"), [[1.0], [2.0]]),
    )
    found = document(path)
    assert found["capacities"] == {}
    assert found["unmet_demand_timeseries"] == [1.0, 2.0]
    assert found["unmet_demand_by_location"] == {"hub": 3.0}
    assert found["objective"] == 0.0
    assert found["details"] == {"cost_of_unmet_demand": 1500.0}
    assert found["warnings"] == []


def test_the_costs_of_a_store_and_of_spilling_are_counted(tmp_path: Path) -> None:
    path = _network(
        tmp_path,
        objective=0.5 * 7 + 2.0 * 3 + 1.0 * 10 + 3.0 * 4,
        storage_units_i=(("storage_units_i",), ["dam"]),
        storage_units_bus=(("storage_units_i",), ["hub"]),
        storage_units_p_nom_opt=(("storage_units_i",), [10.0]),
        storage_units_marginal_cost=(("storage_units_i",), [0.5]),
        storage_units_marginal_cost_storage=(("storage_units_i",), [2.0]),
        storage_units_spill_cost=(("storage_units_i",), [1.0]),
        storage_units_t_p_i=(("storage_units_t_p_i",), ["dam"]),
        storage_units_t_p=(("snapshots", "storage_units_t_p_i"), [[7.0], [-5.0]]),
        storage_units_t_p_dispatch_i=(("storage_units_t_p_dispatch_i",), ["dam"]),
        storage_units_t_p_dispatch=(("snapshots", "storage_units_t_p_dispatch_i"), [[7.0], [0.0]]),
        storage_units_t_state_of_charge_i=(("storage_units_t_state_of_charge_i",), ["dam"]),
        storage_units_t_state_of_charge=(
            ("snapshots", "storage_units_t_state_of_charge_i"),
            [[1.0], [2.0]],
        ),
        storage_units_t_spill_i=(("storage_units_t_spill_i",), ["dam"]),
        storage_units_t_spill=(("snapshots", "storage_units_t_spill_i"), [[4.0], [6.0]]),
        stores_i=(("stores_i",), ["tank"]),
        stores_bus=(("stores_i",), ["hub"]),
        stores_e_nom_opt=(("stores_i",), [40.0]),
        stores_marginal_cost_quadratic=(("stores_i",), [3.0]),
        stores_t_p_i=(("stores_t_p_i",), ["tank"]),
        stores_t_p=(("snapshots", "stores_t_p_i"), [[2.0], [0.0]]),
    )
    found = document(path)
    # dam: 0.5 per unit dispatched, 2 per unit held, 1 per unit spilled; tank: 3 per unit squared
    assert found["costs_by_location"] == {"hub": {"dam": 3.5 + 6.0 + 10.0, "tank": 12.0}}
    assert found["dispatch"] == {"dam": [7.0, 0.0], "tank": [2.0, 0.0]}
    assert found["warnings"] == []


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


# -- power flow -------------------------------------------------------------------------------


def power_flow(tmp_path: Path, **changes: object) -> Path:
    """A network solved by a power flow: a grid feeding a town over a line and a transformer.

    The high-voltage bus holds its voltage, so PyPSA writes no magnitude for
    it, and no angle, which is zero at the slack. A bus of heat is no part
    of the electrical network. The transformer has no rating.
    """
    return _network(
        tmp_path,
        objective=None,
        buses_i=(("buses_i",), ["hv::electricity", "mv::electricity", "mv::heat"]),
        buses_carrier=(("buses_i",), ["AC", "AC", "heat"]),
        sub_networks_i=(("sub_networks_i",), ["0", "1"]),
        sub_networks_slack_bus=(("sub_networks_i",), ["hv::electricity", "mv::heat"]),
        buses_t_v_mag_pu_i=(("buses_t_v_mag_pu_i",), ["mv::electricity"]),
        buses_t_v_mag_pu=(("snapshots", "buses_t_v_mag_pu_i"), [[0.98], [0.97]]),
        buses_t_v_ang_i=(("buses_t_v_ang_i",), ["mv::electricity"]),
        buses_t_v_ang=(("snapshots", "buses_t_v_ang_i"), [[-0.05], [-0.06]]),
        generators_i=(("generators_i",), ["grid", "pv"]),
        generators_bus=(("generators_i",), ["hv::electricity", "mv::electricity"]),
        generators_p_nom=(("generators_i",), [100.0, 10.0]),
        generators_t_p_i=(("generators_t_p_i",), ["grid", "pv"]),
        generators_t_p=(("snapshots", "generators_t_p_i"), [[7.0, 3.0], [8.5, 1.5]]),
        generators_t_q_i=(("generators_t_q_i",), ["pv"]),
        generators_t_q=(("snapshots", "generators_t_q_i"), [[0.5], [-0.5]]),
        loads_i=(("loads_i",), ["town"]),
        loads_bus=(("loads_i",), ["mv::electricity"]),
        loads_t_p_i=(("loads_t_p_i",), ["town"]),
        loads_t_p=(("snapshots", "loads_t_p_i"), [[10.0], [10.0]]),
        lines_i=(("lines_i",), ["cable"]),
        lines_bus0=(("lines_i",), ["hv::electricity"]),
        lines_bus1=(("lines_i",), ["mv::electricity"]),
        lines_s_nom=(("lines_i",), [10.0]),
        lines_t_p0_i=(("lines_t_p0_i",), ["cable"]),
        lines_t_p0=(("snapshots", "lines_t_p0_i"), [[3.0], [4.0]]),
        lines_t_p1_i=(("lines_t_p1_i",), ["cable"]),
        lines_t_p1=(("snapshots", "lines_t_p1_i"), [[-2.9], [-3.9]]),
        lines_t_q0_i=(("lines_t_q0_i",), ["cable"]),
        lines_t_q0=(("snapshots", "lines_t_q0_i"), [[4.0], [3.0]]),
        transformers_i=(("transformers_i",), ["station"]),
        transformers_bus0=(("transformers_i",), ["hv::electricity"]),
        transformers_bus1=(("transformers_i",), ["mv::electricity"]),
        transformers_t_p0_i=(("transformers_t_p0_i",), ["station"]),
        transformers_t_p0=(("snapshots", "transformers_t_p0_i"), [[4.0], [4.5]]),
        transformers_t_p1_i=(("transformers_t_p1_i",), ["station"]),
        transformers_t_p1=(("snapshots", "transformers_t_p1_i"), [[-4.0], [-4.5]]),
        **changes,
    )


def record(tmp_path: Path, text: str) -> Path:
    """Write a record of the convergence next to the network, as MEME does."""
    path = tmp_path / "power_flow" / "convergence.csv"
    path.parent.mkdir()
    path.write_text(text, encoding="utf-8")
    return path


def test_a_network_solved_by_a_power_flow(tmp_path: Path) -> None:
    found = document(power_flow(tmp_path))
    assert found["success"] is True
    assert found["termination_condition"] == "unknown"
    assert found["objective"] is None
    assert "objective_function_value" not in found
    assert found["costs_by_location"] == {}
    assert found["capacities"] == {
        "hv::grid": 100.0,
        "mv::pv": 10.0,
        "hv::cable": 10.0,
        "mv::cable": 10.0,
        "hv::station": 0.0,
        "mv::station": 0.0,
    }
    assert found["dispatch"] == {"grid": [7.0, 8.5], "pv": [3.0, 1.5]}
    assert found["demand_timeseries"] == [10.0, 10.0]
    assert found["transmission_flow"] == {
        "hv::mv": {"from": "hv", "to": "mv", "timeseries": [6.9, 8.4]}
    }
    assert found["warnings"] == [
        (
            "the network holds the solution of a power flow, not of an optimisation: the"
            " capacities are those given, and the document has no costs; PyPSA does not record"
            " whether the power flow converged, and no record lies next to the file"
            " (power_flow/convergence.csv)"
        )
    ]


def test_what_a_power_flow_finds(tmp_path: Path) -> None:
    found = document(power_flow(tmp_path))
    # The voltage of the slack is the default; the bus of heat has none. The loading is the
    # apparent power at the fuller end over the rating: sqrt(3² + 4²) / 10, sqrt(4² + 3²) / 10.
    # The transformer has no rating, so its loading is no number.
    assert found["details"] == {
        "power_flow": {
            "slack_buses": ["hv::electricity", "mv::heat"],
            "voltage_magnitude": {"hv::electricity": [1.0, 1.0], "mv::electricity": [0.98, 0.97]},
            "voltage_angle": {"hv::electricity": [0.0, 0.0], "mv::electricity": [-0.05, -0.06]},
            "reactive_power": {"hv::grid": [0.0, 0.0], "mv::pv": [0.5, -0.5]},
            "branch_loading": {"cable": [0.5, 0.5], "station": [None, None]},
        }
    }


def test_a_power_flow_without_reactive_results(tmp_path: Path) -> None:
    path = power_flow(tmp_path)
    with files.netCDF4.Dataset(path, "a") as dataset:
        dataset.renameVariable("generators_t_q", "generators_t_q_gone")
        dataset.renameVariable("lines_t_q0", "lines_t_q0_gone")
    found = document(path)
    assert "reactive_power" not in found["details"]["power_flow"]
    assert found["details"]["power_flow"]["branch_loading"]["cable"] == [0.3, 0.4]


def test_a_linear_power_flow_leaves_every_voltage_at_its_nominal_value(tmp_path: Path) -> None:
    path = power_flow(tmp_path)
    with files.netCDF4.Dataset(path, "a") as dataset:
        dataset.renameVariable("buses_t_v_mag_pu", "buses_t_v_mag_pu_gone")
    found = document(path)
    assert found["success"] is True
    assert found["details"]["power_flow"]["voltage_magnitude"] == {
        "hv::electricity": [1.0, 1.0],
        "mv::electricity": [1.0, 1.0],
    }


def test_the_convergence_is_taken_from_the_record_next_to_the_file(tmp_path: Path) -> None:
    record(tmp_path, "snapshot,converged,iterations\n0,True,3\n1,True,2\n")
    found = document(power_flow(tmp_path))
    assert found["success"] is True
    assert found["termination_condition"] == "converged"
    assert found["details"]["power_flow"]["converged"] == [True, True]
    assert found["details"]["power_flow"]["iterations"] == [3, 2]
    assert found["warnings"] == [
        (
            "the network holds the solution of a power flow, not of an optimisation: the"
            " capacities are those given, and the document has no costs"
        )
    ]


def test_a_record_may_leave_out_the_iterations(tmp_path: Path) -> None:
    record(tmp_path, "snapshot,converged\n0,true\n1,TRUE\n")
    found = document(power_flow(tmp_path))
    assert found["termination_condition"] == "converged"
    assert found["details"]["power_flow"]["converged"] == [True, True]
    assert "iterations" not in found["details"]["power_flow"]


def test_a_power_flow_that_did_not_converge(tmp_path: Path) -> None:
    record(tmp_path, "snapshot,converged,iterations\n0,True,3\n1,False,100\n")
    found = document(power_flow(tmp_path))
    assert found["success"] is False
    assert found["termination_condition"] == "not_converged"
    assert found["details"]["power_flow"]["converged"] == [True, False]
    assert found["warnings"] == [
        (
            "the network holds the solution of a power flow, not of an optimisation: the"
            " capacities are those given, and the document has no costs; the record next to"
            " the file says that the power flow did not converge in 1 of 2 snapshots"
        )
    ]


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("snapshot,converged\n0,True\n", "it has 1 rows, the network 2 snapshots"),
        ("snapshot,solved\n0,True\n1,True\n", "it has no column 'converged'"),
        (
            "snapshot,converged\n0,True\n1,maybe\n",
            "its column 'converged' is not all true or false",
        ),
        (b"\xff\xfe", "it cannot be read (UnicodeDecodeError)"),
    ],
)
def test_a_record_that_does_not_fit_the_network_is_not_used(
    tmp_path: Path, text: str | bytes, problem: str
) -> None:
    path = record(tmp_path, "")
    path.write_bytes(text) if isinstance(text, bytes) else path.write_text(text)
    found = document(power_flow(tmp_path))
    assert found["success"] is True
    assert found["termination_condition"] == "unknown"
    assert "converged" not in found["details"]["power_flow"]
    assert found["warnings"][0].endswith(
        f"the record next to the file (power_flow/convergence.csv) cannot be used: {problem}"
    )


def test_a_record_with_iterations_that_are_no_numbers_keeps_the_convergence(
    tmp_path: Path,
) -> None:
    record(tmp_path, "snapshot,converged,iterations\n0,True,\n1,True,2\n")
    found = document(power_flow(tmp_path))
    assert found["termination_condition"] == "converged"
    assert "iterations" not in found["details"]["power_flow"]


def test_a_network_with_a_power_flow_record_but_no_results_is_not_solved(tmp_path: Path) -> None:
    record(tmp_path, "snapshot,converged\n0,True\n1,True\n")
    found = document(files.pypsa_netcdf(tmp_path / "network.nc", solved=False))
    assert found["success"] is False
    assert found["termination_condition"] == "not_solved"
    assert "power_flow" not in found["details"]


def test_a_power_flow_of_one_bus_has_voltages_alone(tmp_path: Path) -> None:
    path = _network(
        tmp_path,
        objective=None,
        buses_t_p_i=(("buses_t_p_i",), ["hub"]),
        buses_t_p=(("snapshots", "buses_t_p_i"), [[1.0], [2.0]]),
    )
    found = document(path)
    assert found["success"] is True
    assert found["termination_condition"] == "unknown"
    assert found["details"] == {
        "power_flow": {
            "voltage_magnitude": {"hub": [1.0, 1.0]},
            "voltage_angle": {"hub": [0.0, 0.0]},
        }
    }


# -- prices, emissions and levels -------------------------------------------------------------


def test_the_price_of_a_bus_is_named_by_location_and_carrier(tmp_path: Path) -> None:
    # A bus named north::electricity is the price of electricity at north; a bus named with
    # more parts keeps its name; any other bus is named by its location and its carrier.
    path = _network(
        tmp_path,
        buses_i=(("buses_i",), ["hub::power", "hub::power::tank", "plain"]),
        buses_carrier=(("buses_i",), ["AC", "AC", "gas"]),
        buses_t_marginal_price_i=(("buses_t_marginal_price_i",), ["hub::power", "plain"]),
        buses_t_marginal_price=(
            ("snapshots", "buses_t_marginal_price_i"),
            [[5.0, 1.0], [6.0, 1.0]],
        ),
    )
    found = document(path)
    assert found["prices"] == {
        "hub::power": [5.0, 6.0],
        "hub::power::tank": [0.0, 0.0],
        "plain::gas": [1.0, 1.0],
    }


def test_a_store_that_is_not_cyclic_emits_what_it_gives_off(tmp_path: Path) -> None:
    # The tank of gas starts with 10 and ends with 4: it gave off 6 at 0.5 a unit. The dam is
    # cyclic and emits nothing, whatever it holds.
    path = _network(
        tmp_path,
        objective=0.0,
        buses_i=(("buses_i",), ["hub::gas", "hub::power"]),
        carriers_i=(("carriers_i",), ["gas", "water"]),
        carriers_co2_emissions=(("carriers_i",), [0.5, 0.0]),
        stores_i=(("stores_i",), ["tank"]),
        stores_bus=(("stores_i",), ["hub::gas"]),
        stores_carrier=(("stores_i",), ["gas"]),
        stores_e_initial=(("stores_i",), [10.0]),
        stores_e_nom_opt=(("stores_i",), [10.0]),
        stores_t_e_i=(("stores_t_e_i",), ["tank"]),
        stores_t_e=(("snapshots", "stores_t_e_i"), [[7.0], [4.0]]),
        storage_units_i=(("storage_units_i",), ["dam"]),
        storage_units_bus=(("storage_units_i",), ["hub::power"]),
        storage_units_carrier=(("storage_units_i",), ["gas"]),
        storage_units_cyclic_state_of_charge=(("storage_units_i",), np.array([True])),
        storage_units_p_nom_opt=(("storage_units_i",), [3.0]),
        storage_units_t_state_of_charge_i=(("storage_units_t_state_of_charge_i",), ["dam"]),
        storage_units_t_state_of_charge=(
            ("snapshots", "storage_units_t_state_of_charge_i"),
            [[2.0], [1.0]],
        ),
        generators_i=(("generators_i",), ["ccgt"]),
        generators_bus=(("generators_i",), ["hub::power"]),
        generators_carrier=(("generators_i",), ["gas"]),
        generators_efficiency=(("generators_i",), [0.5]),
        generators_p_nom_opt=(("generators_i",), [10.0]),
        generators_t_p_i=(("generators_t_p_i",), ["ccgt"]),
        generators_t_p=(("snapshots", "generators_t_p_i"), [[4.0], [2.0]]),
    )
    found = document(path)
    # The plant burns 8 and 4 of gas for 4 and 2 of power.
    assert found["emissions_by_location"] == {"hub::tank": 3.0, "hub::ccgt": 6.0}
    assert found["total_emissions"] == 9.0
    assert found["storage_levels"] == {"hub::tank": [7.0, 4.0], "hub::dam": [2.0, 1.0]}


def test_without_emitting_carriers_there_are_no_emissions(tmp_path: Path) -> None:
    path = _network(
        tmp_path,
        carriers_i=(("carriers_i",), ["wind"]),
        generators_i=(("generators_i",), ["turbine"]),
        generators_bus=(("generators_i",), ["hub"]),
        generators_carrier=(("generators_i",), ["wind"]),
        generators_t_p_i=(("generators_t_p_i",), ["turbine"]),
        generators_t_p=(("snapshots", "generators_t_p_i"), [[4.0], [2.0]]),
    )
    found = document(path)
    assert "emissions_by_location" not in found
    assert "curtailment" not in found


def test_a_store_that_was_never_filled_held_nothing(tmp_path: Path) -> None:
    path = _network(
        tmp_path,
        stores_i=(("stores_i",), ["tank"]),
        stores_bus=(("stores_i",), ["hub"]),
        stores_e_nom_opt=(("stores_i",), [10.0]),
    )
    assert document(path)["storage_levels"] == {"hub::tank": [0.0, 0.0]}


def test_scenarios_blend_the_levels_the_prices_and_the_emissions(tmp_path: Path) -> None:
    path = files.write_netcdf(
        tmp_path / "network.nc",
        {
            "attributes": {"network_pypsa_version": "1.2.4", "network__objective": 0.0},
            "dimensions": {"snapshots": 2, "scenario": 2, "generators_i": 1, "buses_i": 1,
                           "carriers_i": 1, "generators_t_p_i": 1, "buses_t_marginal_price_i": 1},
            "variables": {
                "snapshots": (("snapshots",), np.arange(2)),
                "scenario": (("scenario",), ["dear", "cheap"]),
                "scenario_weight": (("scenario",), [0.5, 0.5]),
                "buses_i": (("buses_i",), ["hub::power"]),
                "carriers_i": (("carriers_i",), ["gas"]),
                "carriers_co2_emissions": (("carriers_i",), [1.0]),
                "generators_i": (("generators_i",), ["gas"]),
                "generators_bus": (("scenario", "generators_i"), [["hub::power"], ["hub::power"]]),
                "generators_carrier": (("scenario", "generators_i"), [["gas"], ["gas"]]),
                "generators_p_nom_opt": (("scenario", "generators_i"), [[10.0], [10.0]]),
                "generators_t_p_i": (("generators_t_p_i",), ["gas"]),
                "generators_t_p": (
                    ("snapshots", "scenario", "generators_t_p_i"),
                    [[[2.0], [6.0]], [[4.0], [8.0]]],
                ),
                "buses_t_marginal_price_i": (("buses_t_marginal_price_i",), ["hub::power"]),
                "buses_t_marginal_price": (
                    ("snapshots", "scenario", "buses_t_marginal_price_i"),
                    [[[10.0], [20.0]], [[30.0], [50.0]]],
                ),
            },
        },
    )  # fmt: skip
    found = document(path)
    assert found["emissions_by_location"] == {"hub::gas": 0.5 * 6 + 0.5 * 14}
    assert found["prices"] == {"hub::power": [15.0, 40.0]}
    assert found["fixed_costs_by_location"] == {"hub": {"gas": 0.0}}
