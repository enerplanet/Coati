"""The results of AdOpT-NET0, from files made for the tests."""

from __future__ import annotations

from pathlib import Path

import h5py
import pytest

import coati
from coati.errors import ExtractionError
from support import files
from support.compare import as_json


def document(path: Path, framework: str = "auto", **options: object) -> dict:
    return as_json(coati.results_document(path, framework, coati.ExtractOptions(**options)))


@pytest.fixture
def solved(tmp_path: Path) -> dict:
    return document(files.adopt_net0(tmp_path / "optimization_results.h5"))


def test_run_is_described(solved: dict) -> None:
    assert solved["framework"] == "adopt-net0"
    assert solved["framework_version"] is None
    assert solved["model_name"] == "synthetic"
    assert solved["solver"] is None
    assert solved["success"] is True
    assert solved["termination_condition"] == "optimal"
    assert solved["objective"] == files.ADOPT_COST
    assert solved["objective_function_value"] == files.ADOPT_COST
    assert solved["metadata"]["framework_id"] == "adopt-net0-v0-1"
    assert solved["warnings"] == []


def test_the_version_is_that_of_the_identifier(tmp_path: Path) -> None:
    path = files.adopt_net0(tmp_path / "optimization_results.h5")
    found = document(path, "adopt-net0-v0-1-10")
    assert found["framework_version"] == "0.1.10"
    assert found["metadata"]["framework_id"] == "adopt-net0-v0-1-10"


def test_timestamps_are_positions_because_the_file_records_no_times(solved: dict) -> None:
    assert solved["timestamps"] == [0, 1, 2]
    assert "weights" not in solved


def test_timestamps_can_be_given_by_the_caller(tmp_path: Path) -> None:
    path = files.adopt_net0(tmp_path / "optimization_results.h5")
    found = document(path, time_start="2030-01-01", time_step="30min")
    assert found["timestamps"] == [
        "2030-01-01T00:00:00",
        "2030-01-01T00:30:00",
        "2030-01-01T01:00:00",
    ]


def test_capacity_is_the_size_times_the_rated_power(solved: dict) -> None:
    # Two wind turbines of 1.5 each.
    assert solved["capacities"]["a::Wind"] == 3.0


def test_the_size_of_a_store_is_the_energy_it_holds(solved: dict) -> None:
    assert solved["capacities"]["b::Battery"] == 8.0
    assert solved["storage_capacities"] == {"b::Battery": 8.0}


def test_arcs_are_named_by_their_nodes_not_by_their_group(solved: dict) -> None:
    assert solved["capacities"]["a::cable:b"] == 5.0
    assert solved["capacities"]["b::cable:a"] == 5.0


def test_generation(solved: dict) -> None:
    assert solved["generation"] == {
        "a::Wind::power": 6.0,
        "b::Battery::power": 1.0,
        "a::import_power::power": 9.0,
        "b::cable:a::power": 10.5,
        "a::cable:b::power": 0.0,
    }


def test_imports_are_reported_like_a_technology(solved: dict) -> None:
    assert solved["dispatch"] == {
        "Wind": [3.0, 2.0, 1.0],
        "Battery": [0.0, 1.0, 0.0],
        "import_power": [2.0, 3.0, 4.0],
    }
    assert solved["tech_metadata"]["import_power"] == {"parent": "supply", "carrier_out": "power"}


def test_what_a_solver_leaves_behind_is_no_export(solved: dict) -> None:
    # The node a exports one billionth of a unit in the last hour.
    assert solved["details"]["exported"] == {"b::power": 0.5}
    assert "export_power" not in solved["costs_by_location"]["a"]


def test_transmission_is_what_arrives_after_the_losses(solved: dict) -> None:
    assert solved["transmission_flow"] == {
        "a::b": {"from": "a", "to": "b", "timeseries": [3.5, 3.5, 3.5]}
    }


def test_demand(solved: dict) -> None:
    assert solved["demand_timeseries"] == [4.0, 5.0, 4.0]
    assert solved["demand_by_location"] == {"b": 13.0}


def test_costs(solved: dict) -> None:
    # The cable costs 10 to build and 1 to run from a to b; its two directions share the 10.
    assert solved["costs_by_location"] == {
        "a": {
            "Wind": 60.0 + 6.0 + 4.0,
            "import_power": 2 * 10 + 3 * 10 + 4 * 20,
            "cable:b": 10.0 / 2 + 1.0,
        },
        "b": {
            "Battery": 30.0,
            "export_power": -(0.5 * 2),
            "cable:a": 10.0 / 2,
        },
    }


def test_a_connection_in_both_directions_is_charged_once(solved: dict) -> None:
    network = [
        cost
        for costs in solved["costs_by_location"].values()
        for technology, cost in costs.items()
        if technology.startswith("cable:")
    ]
    assert sum(network) == 11.0


def test_the_costs_add_up_to_the_objective(solved: dict) -> None:
    total = sum(sum(costs.values()) for costs in solved["costs_by_location"].values())
    assert total == 70.0 + 130.0 + 11.0 + 30.0 - 1.0
    assert total == solved["objective"]


def test_costs_by_technology_list_what_costs_something(solved: dict) -> None:
    assert solved["costs_by_tech"] == {
        "Wind": 70.0,
        "import_power": 130.0,
        "cable:b": 6.0,
        "Battery": 30.0,
        "cable:a": 5.0,
    }


def test_the_kind_of_a_technology_follows_from_what_it_does(solved: dict) -> None:
    assert solved["tech_parents"] == {
        "Wind": "supply",
        "Battery": "storage",
        "import_power": "supply",
        "export_power": "demand",
        "cable": "transmission",
        "cable:a": "transmission",
        "cable:b": "transmission",
    }
    assert solved["tech_metadata"]["cable:b"] == solved["tech_metadata"]["cable"]


def test_the_summary_is_reported_without_the_folder_of_the_run(solved: dict) -> None:
    summary = solved["details"]["summary"]
    assert summary["total_npv"] == files.ADOPT_COST
    assert summary["solver_status"] == "optimal"
    assert summary["objective"] == "costs"
    assert "time_stamp" not in summary
    assert "/home/someone" not in str(solved)


def test_figures_that_are_not_set_are_left_out(solved: dict) -> None:
    assert "pareto_point" not in solved["details"]["summary"]


def test_the_first_period_is_reported(tmp_path: Path) -> None:
    path = files.adopt_net0(tmp_path / "results.h5", periods=("early", "late"))
    found = document(path)
    assert found["capacities"]["a::Wind"] == 3.0
    assert found["details"]["periods"] == ["early", "late"]
    assert found["details"]["period"] == "early"
    assert found["warnings"] == [
        (
            "the file holds 2 investment periods; the document reports 'early',"
            " and its objective is the cost of that period"
        )
    ]


def test_the_objective_is_the_cost_of_the_period(tmp_path: Path) -> None:
    path = files.adopt_net0(tmp_path / "results.h5", periods=("early", "late"))
    early, late = document(path), document(path, period="late")
    assert early["objective"] == files.ADOPT_COST
    assert late["objective"] == 2 * files.ADOPT_COST
    for found in (early, late):
        assert found["objective_function_value"] == 3 * files.ADOPT_COST
        assert found["details"]["summary"]["total_npv"] == 3 * files.ADOPT_COST
        total = sum(sum(costs.values()) for costs in found["costs_by_location"].values())
        assert total == found["objective"]


def test_periods_that_hold_the_same_results_are_pointed_out(tmp_path: Path) -> None:
    # AdOpT-NET0 0.1.10 writes the results of the last period for every period.
    path = files.adopt_net0(tmp_path / "results.h5", periods=("early", "late"), alike=True)
    found = document(path)
    assert found["details"]["period"] == "early"
    assert found["capacities"]["a::Wind"] == 6.0
    assert found["capacities"]["a::cable:b"] == 5.0
    assert found["warnings"][1] == (
        "the file holds the same results for each of its 2 investment periods, except for"
        " the design of the networks; AdOpT-NET0 0.1.10 is known to write the results of"
        " the last period, 'late', in place of those of every period"
    )
    assert len(found["warnings"]) == 2


def test_another_period_can_be_asked_for(tmp_path: Path) -> None:
    path = files.adopt_net0(tmp_path / "results.h5", periods=("early", "late"))
    found = document(path, period="late")
    assert found["capacities"]["a::Wind"] == 6.0
    assert found["dispatch"]["Wind"] == [6.0, 4.0, 2.0]
    assert found["details"]["period"] == "late"


def test_a_period_that_the_file_lacks_is_refused(tmp_path: Path) -> None:
    path = files.adopt_net0(tmp_path / "results.h5")
    with pytest.raises(ExtractionError, match="no investment period 'late'; the file has period1"):
        coati.results_document(path, options=coati.ExtractOptions(period="late"))


def test_groups_are_found_whatever_the_case_of_their_names(tmp_path: Path) -> None:
    lower = document(files.adopt_net0(tmp_path / "lower.h5"))
    upper = document(files.adopt_net0(tmp_path / "upper.h5", capitalised=True))
    for found in (lower, upper):
        del found["metadata"]["source"]
    assert lower == upper


def test_typical_days_stand_for_the_whole_time(tmp_path: Path) -> None:
    # The file has three times, those of the typical days; the second stands for two times.
    cost = (60 + 6 + 4 * 8 / 6) + 30 + (10 + 1 * 16 / 12) + (20 + 30 + 30 + 80) - 1
    path = files.adopt_net0(
        tmp_path / "results.h5", typical_days=1, summary={"total_npv": cost, "total_cost": cost}
    )
    found = document(path)
    assert found["details"]["typical_days"] is True
    assert found["timestamps"] == [0, 1, 2, 3]
    assert "weights" not in found
    assert found["dispatch"]["Wind"] == [3.0, 2.0, 2.0, 1.0]
    assert found["generation"]["a::Wind::power"] == 8.0
    assert found["demand_timeseries"] == [4.0, 5.0, 5.0, 4.0]
    assert found["demand_by_location"] == {"b": 18.0}
    assert found["transmission_flow"]["a::b"]["timeseries"] == [3.5, 3.5, 3.5, 3.5]
    assert found["costs_by_location"]["a"]["import_power"] == 20 + 30 + 30 + 80
    assert found["costs_by_location"]["a"]["Wind"] == pytest.approx(60 + 6 + 4 * 8 / 6)
    assert found["costs_by_location"]["a"]["cable:b"] == pytest.approx(10 / 2 + 1 * 16 / 12)
    assert found["objective"] == pytest.approx(cost)
    assert found["warnings"] == []


def test_typical_days_with_the_series_of_the_whole_time(tmp_path: Path) -> None:
    found = document(files.adopt_net0(tmp_path / "results.h5", typical_days=2))
    plain = document(files.adopt_net0(tmp_path / "plain.h5"))
    assert found["details"].pop("typical_days") is True
    for document_ in (found, plain):
        del document_["metadata"]["source"]
    assert found == plain


def test_times_can_be_given_for_the_whole_time(tmp_path: Path) -> None:
    path = files.adopt_net0(tmp_path / "results.h5", typical_days=1)
    found = document(path, time_start="2030-01-01", time_step="1h")
    assert found["timestamps"][-1] == "2030-01-01T03:00:00"
    assert len(found["timestamps"]) == 4


def test_costs_that_belong_to_no_technology_are_named(tmp_path: Path) -> None:
    summary = {"carbon_cost": 15.0, "carbon_revenue": 5.0, "total_npv": 250.0, "total_cost": 250.0}
    found = document(files.adopt_net0(tmp_path / "results.h5", summary=summary))
    assert found["objective"] == 250.0
    assert found["warnings"] == [
        (
            "the total cost of 250 includes costs that belong to no technology and are not"
            " listed: carbon_cost 15, carbon_revenue 5"
        )
    ]


def test_a_total_that_the_costs_do_not_explain(tmp_path: Path) -> None:
    summary = {"total_npv": 300.0}
    found = document(files.adopt_net0(tmp_path / "results.h5", summary=summary))
    assert found["objective"] == 300.0
    assert found["warnings"] == [
        (
            "the total cost is 300, the costs that the file attributes to technologies,"
            " networks and carriers add up to 240"
        )
    ]


def test_an_objective_other_than_the_cost(tmp_path: Path) -> None:
    summary = {"objective": "emissions_net"}
    found = document(files.adopt_net0(tmp_path / "results.h5", summary=summary))
    assert found["objective"] == files.ADOPT_COST
    assert "objective_function_value" not in found


def test_a_run_that_was_stopped(tmp_path: Path) -> None:
    path = files.adopt_net0(tmp_path / "results.h5", summary={"solver_status": "maxTimeLimit"})
    found = document(path)
    assert found["success"] is False
    assert found["termination_condition"] == "maxTimeLimit"
    # The file holds the best solution that was found.
    assert found["objective"] == files.ADOPT_COST
    assert found["capacities"]["a::Wind"] == 3.0


def test_the_total_cost_stands_in_for_a_missing_present_value(tmp_path: Path) -> None:
    path = files.adopt_net0(tmp_path / "results.h5")
    with h5py.File(path, "a") as file:
        del file["summary/total_npv"]
        file["summary/total_cost"][()] = 250.0
        file["summary/violation_cost"][()] = 10.0
    found = document(path)
    assert found["objective"] == 250.0
    assert found["objective_function_value"] == 250.0


def test_a_summary_without_a_total_leaves_the_costs_to_be_added_up(tmp_path: Path) -> None:
    path = files.adopt_net0(tmp_path / "results.h5")
    with h5py.File(path, "a") as file:
        del file["summary/total_npv"], file["summary/total_cost"], file["summary/solver_status"]
    found = document(path)
    assert found["objective"] == files.ADOPT_COST
    assert "objective_function_value" not in found
    assert found["termination_condition"] == "unknown"
    assert found["success"] is False


def test_an_arc_that_does_not_name_its_nodes_is_left_out(tmp_path: Path) -> None:
    path = files.adopt_net0(tmp_path / "results.h5")
    with h5py.File(path, "a") as file:
        del file["design/networks/period1/cable/ba/toNode"]
    found = document(path)
    assert "b::cable:a" not in found["capacities"]
    assert found["capacities"]["a::cable:b"] == 5.0
    assert found["warnings"] == [
        "the arc 'ba' of the network 'cable' does not name its nodes; it is not reported"
    ]


def test_a_directory_with_one_file_of_results_is_a_source(tmp_path: Path) -> None:
    folder = tmp_path / "results" / "20260928-1"
    folder.mkdir(parents=True)
    files.adopt_net0(folder / "optimization_results.h5")
    assert document(tmp_path)["objective"] == files.ADOPT_COST


def several_carriers(path: Path) -> Path:
    """Add heat to the model: a boiler that makes it and a sink that takes it."""
    files.adopt_net0(path)
    with h5py.File(path, "a") as file:
        del file["topology/carriers"]
        file["topology"].create_dataset("carriers", data=["power", "heat"])
        for name, flows in (
            ("Boiler", {"power_input": [2.0, 2, 2], "heat_output": [1.8, 1.8, 1.8]}),
            ("Sink", {"heat_input": [1.8, 1.8, 1.8], "unknown_output": [9.0, 9, 9]}),
        ):
            sized = file.create_group(f"design/nodes/period1/b/{name}")
            sized.create_dataset("size", data=[2.0])
            for part in ("capex_tot", "opex_fixed_tot", "opex_variable"):
                sized.create_dataset(part, data=[0.0])
            running = file.create_group(f"operation/technology_operation/period1/b/{name}")
            for flow, values in flows.items():
                running.create_dataset(flow, data=values)
        file.move("design/networks/period1/cable", "design/networks/period1/powerOnshore")
        file.move("operation/networks/period1/cable", "operation/networks/period1/powerOnshore")
    return path


def test_the_kind_of_a_technology_with_several_carriers(tmp_path: Path) -> None:
    found = document(several_carriers(tmp_path / "results.h5"))
    assert found["tech_metadata"]["Boiler"] == {"parent": "conversion", "carrier_out": "heat"}
    assert found["tech_metadata"]["Sink"] == {"parent": "demand", "carrier_out": ""}
    assert found["generation"]["b::Boiler::heat"] == pytest.approx(5.4)
    assert found["dispatch"]["Boiler"] == [1.8, 1.8, 1.8]
    assert "Sink" not in found["dispatch"]
    # "unknown" is no carrier of the model: the series is no flow.
    assert not any(key.startswith("b::Sink") for key in found["generation"])


def test_the_carrier_of_a_network_is_the_one_its_name_starts_with(tmp_path: Path) -> None:
    found = document(several_carriers(tmp_path / "results.h5"))
    assert found["tech_metadata"]["powerOnshore"]["carrier_out"] == "power"
    assert found["tech_metadata"]["powerOnshore:b"]["carrier_out"] == "power"
    assert found["generation"]["b::powerOnshore:a::power"] == 10.5


def test_a_network_whose_carrier_is_not_known(tmp_path: Path) -> None:
    path = several_carriers(tmp_path / "results.h5")
    with h5py.File(path, "a") as file:
        file.move("design/networks/period1/powerOnshore", "design/networks/period1/cable")
        file.move("operation/networks/period1/powerOnshore", "operation/networks/period1/cable")
    found = document(path)
    assert found["tech_metadata"]["cable"] == {"parent": "transmission", "carrier_out": ""}
    assert found["capacities"]["a::cable:b"] == 5.0
    assert found["transmission_flow"]["a::b"]["timeseries"] == [3.5, 3.5, 3.5]
    assert not any("cable" in key for key in found["generation"])


def test_an_arc_that_was_not_operated(tmp_path: Path) -> None:
    path = files.adopt_net0(tmp_path / "results.h5")
    with h5py.File(path, "a") as file:
        del file["operation/networks"]
    found = document(path)
    assert found["capacities"]["a::cable:b"] == 5.0
    assert found["transmission_flow"] == {}
    assert found["costs_by_location"]["a"]["cable:b"] == 6.0


def test_periods_are_those_of_the_design_if_the_topology_names_none(tmp_path: Path) -> None:
    path = files.adopt_net0(tmp_path / "results.h5", periods=("early", "late"))
    with h5py.File(path, "a") as file:
        del file["topology/periods"]
    found = document(path)
    assert found["details"]["periods"] == ["early", "late"]
    assert found["details"]["period"] == "early"


def test_typical_days_that_the_file_does_not_describe_in_full(tmp_path: Path) -> None:
    path = files.adopt_net0(tmp_path / "results.h5", typical_days=1)
    with h5py.File(path, "a") as file:
        del file["k_means_specs/period1/sequence"]
    found = document(path)
    assert found["details"]["typical_days"] is True
    assert found["timestamps"] == [0, 1, 2]


def test_typical_days_that_point_beyond_the_series(tmp_path: Path) -> None:
    path = files.adopt_net0(tmp_path / "results.h5", typical_days=1)
    with h5py.File(path, "a") as file:
        file["k_means_specs/period1/sequence"][...] = [1, 2, 3, 4]
    assert document(path)["timestamps"] == [0, 1, 2]
