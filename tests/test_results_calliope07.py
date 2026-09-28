"""The results of Calliope 0.7, from files made for the tests."""

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
    return document(files.calliope07(tmp_path / "model.nc"))


def test_run_is_described(solved: dict) -> None:
    assert solved["framework"] == "calliope"
    assert solved["framework_version"] == "0.7.0"
    assert solved["model_name"] == "Synthetic model"
    assert solved["solver"] == "highs"
    assert solved["success"] is True
    assert solved["termination_condition"] == "optimal"
    assert solved["details"] == {"mode": "base"}
    assert solved["warnings"] == []


def test_timestamps_are_iso_8601(solved: dict) -> None:
    assert solved["timestamps"] == files.TIMESTAMPS


def test_weights_are_reported_because_they_differ(solved: dict) -> None:
    assert solved["weights"] == files.WEIGHTS


def test_capacity_is_the_largest_over_the_carriers(solved: dict) -> None:
    assert solved["capacities"] == {
        "a::pv": 10.0,
        "a::line": 5.0,
        "b::load": 8.0,
        "b::battery": 4.0,
        "b::line": 5.0,
    }
    assert solved["storage_capacities"] == {"b::battery": 16.0}


def test_generation_counts_each_time_with_its_weight(solved: dict) -> None:
    assert solved["generation"] == {
        "a::pv::power": 6 + 2 * 8 + 4,
        "a::line::power": 0 + 2 * 0 + 1,
        "b::battery::power": 0 + 2 * 1 + 2,
        "b::line::power": 3 + 2 * 4 + 2,
    }


def test_dispatch_leaves_out_demand_and_transmission(solved: dict) -> None:
    assert solved["dispatch"] == {"pv": [6.0, 8.0, 4.0], "battery": [0.0, 1.0, 2.0]}


def test_transmission_is_the_net_of_both_directions(solved: dict) -> None:
    assert solved["transmission_flow"] == {
        "a::b": {"from": "a", "to": "b", "timeseries": [3.0, 4.0, 1.0]}
    }
    assert solved["imports_by_location"] == {"b": 3 + 2 * 4 + 1}
    assert solved["exports_by_location"] == {"a": 3 + 2 * 4 + 1}


def test_demand(solved: dict) -> None:
    assert solved["demand_timeseries"] == [5.0, 6.0, 7.0]
    assert solved["demand_by_location"] == {"b": 5 + 2 * 6 + 7}


def test_unmet_demand(solved: dict) -> None:
    assert solved["unmet_demand_timeseries"] == [0.0, 0.5, 0.0]
    assert solved["unmet_demand_by_location"] == {"b": 1.0}
    assert solved["total_unmet_demand"] == 1.0


def test_costs_weigh_the_classes_as_the_objective_does(solved: dict) -> None:
    # The class of the emissions counts half: the battery costs 20 + 0.5 * 4.
    assert solved["costs_by_location"] == {
        "a": {"pv": 100.0, "line": 3.0},
        "b": {"battery": 22.0, "line": 3.0},
    }
    assert solved["costs_by_tech"] == {"pv": 100.0, "line": 6.0, "battery": 22.0}
    assert solved["objective"] == 128.0


def test_objective_function_value_is_what_the_solver_reports(solved: dict) -> None:
    assert solved["objective_function_value"] == 127.0


def test_technologies(solved: dict) -> None:
    assert solved["tech_metadata"] == {
        "pv": {
            "parent": "supply",
            "carrier_out": "power",
            "display_name": "Solar",
            "color": "#F9D956",
        },
        "load": {
            "parent": "demand",
            "carrier_out": "",
            "display_name": "Load",
            "color": "#072486",
        },
        "battery": {
            "parent": "storage",
            "carrier_out": "power",
            "display_name": "Battery",
            "color": "#3B61E3",
        },
        "line": {
            "parent": "transmission",
            "carrier_out": "power",
            "display_name": "Line",
            "color": "#8465A9",
        },
    }
    assert solved["tech_parents"] == {
        "pv": "supply",
        "load": "demand",
        "battery": "storage",
        "line": "transmission",
    }


def test_labels_can_be_left_out(tmp_path: Path) -> None:
    found = document(files.calliope07(tmp_path / "model.nc"), labels=False)
    assert found["tech_metadata"]["pv"] == {"parent": "supply", "carrier_out": "power"}


def test_coordinates_are_latitude_then_longitude(solved: dict) -> None:
    assert solved["coordinates"] == {"a": [50.0, 10.0], "b": [51.0, 11.0]}


def test_metadata(solved: dict) -> None:
    metadata = solved["metadata"]
    assert metadata["generator"] == "coati"
    assert metadata["generator_version"] == coati.__version__
    assert metadata["framework_id"] == "calliope-v0-7-0"
    assert metadata["framework_family"] == "calliope-v0-7"
    assert metadata["source"]["name"] == "model.nc"
    assert metadata["source"]["format"] == "netcdf4"
    assert metadata["source"]["size"] > 0


def test_a_preview_states_its_version_in_the_record_of_the_run(tmp_path: Path) -> None:
    found = document(files.calliope07(tmp_path / "model.nc", version="0.7.0.dev7"))
    assert found["framework_version"] == "0.7.0.dev7"
    assert found["metadata"]["framework_id"] == "calliope-v0-7-0-dev7"


def test_the_ends_of_a_line_follow_from_where_it_is_defined(tmp_path: Path) -> None:
    found = document(files.calliope07(tmp_path / "model.nc", links=False))
    assert found["transmission_flow"]["a::b"]["timeseries"] == [3.0, 4.0, 1.0]


def test_spores_report_the_first_and_list_all(tmp_path: Path) -> None:
    found = document(files.calliope07(tmp_path / "model.nc", spores=3))
    assert found["objective"] == 128.0
    assert found["dispatch"]["pv"] == [6.0, 8.0, 4.0]
    assert found["capacities"]["a::pv"] == 10.0
    assert found["details"]["mode"] == "spores"
    spores = found["details"]["spores"]
    assert [entry["spore"] for entry in spores] == ["0", "1", "2"]
    assert [entry["cost"] for entry in spores] == [128.0, 256.0, 384.0]
    assert [entry["capacities"]["a::pv"] for entry in spores] == [10.0, 20.0, 30.0]
    assert [entry["generation"]["a::pv::power"] for entry in spores] == [26.0, 52.0, 78.0]
    assert found["warnings"] == [
        (
            "the file holds 3 solutions of the SPORES mode; the document reports the first,"
            " details.spores lists the cost, the capacities and the generation of each"
        )
    ]


def test_the_first_of_the_spores_is_what_the_document_reports(tmp_path: Path) -> None:
    found = document(files.calliope07(tmp_path / "model.nc", spores=2))
    first = found["details"]["spores"][0]
    assert first["cost"] == found["objective"]
    assert first["capacities"] == found["capacities"]
    assert first["generation"] == found["generation"]


def test_a_single_solution_of_the_spores_mode(tmp_path: Path) -> None:
    found = document(files.calliope07(tmp_path / "model.nc", spores=1))
    assert [entry["spore"] for entry in found["details"]["spores"]] == ["0"]
    assert found["warnings"][0].startswith("the file holds one solution of the SPORES mode;")


def test_operate_mode_takes_the_capacities_from_the_inputs(tmp_path: Path) -> None:
    found = document(files.calliope07(tmp_path / "model.nc", operate=True))
    assert found["capacities"] == {
        "a::pv": 10.0,
        "a::line": 5.0,
        "b::load": 8.0,
        "b::battery": 4.0,
        "b::line": 5.0,
    }
    assert found["objective"] == 128.0
    assert found["objective_function_value"] == 127.0
    assert found["details"]["mode"] == "operate"


def test_a_model_that_is_not_solved(tmp_path: Path) -> None:
    found = document(files.calliope07(tmp_path / "model.nc", solved=False, condition=""))
    assert found["success"] is False
    assert found["termination_condition"] == "not_solved"
    assert found["objective"] is None
    assert found["capacities"] == {}
    assert found["dispatch"] == {}
    assert found["demand_timeseries"] == []
    assert found["timestamps"] == files.TIMESTAMPS
    assert any("not been solved" in warning for warning in found["warnings"])


@pytest.mark.parametrize(
    ("condition", "success"),
    [
        ("optimal", True),
        ("feasible", True),
        ("infeasible", False),
        ("unbounded", False),
        ("maxTimeLimit", False),
    ],
)
def test_success_follows_the_termination_condition(
    tmp_path: Path, condition: str, success: bool
) -> None:
    found = document(files.calliope07(tmp_path / "model.nc", condition=condition))
    assert found["termination_condition"] == condition
    assert found["success"] is success


def test_a_variable_with_unknown_dimensions_is_refused(tmp_path: Path) -> None:
    path = files.write_netcdf(
        tmp_path / "model.nc",
        {
            "groups": {
                "inputs": {
                    "dimensions": {"techs": 1},
                    "variables": {
                        "techs": (("techs",), ["pv"]),
                        "base_tech": (("techs",), ["supply"]),
                    },
                },
                "results": {
                    "dimensions": {"techs": 1, "years": 2},
                    "variables": {
                        "techs": (("techs",), ["pv"]),
                        "flow_cap": (("years", "techs"), [[1.0], [2.0]]),
                    },
                },
                "attrs": {"attributes": {"config": "init:\n  name: x\n", "runtime": "a: b\n"}},
            }
        },
    )
    with pytest.raises(ExtractionError, match=r"flow_cap has the dimensions years, techs"):
        coati.results_document(path)
