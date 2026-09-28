"""The results document and the choices of the caller."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

import coati
from coati import frameworks
from coati.errors import CoatiError, FrameworkError
from coati.results import ExtractOptions, Results, Transmission, extract_results
from coati.results.document import INACTIVE, join, net_flows, positions, succeeded
from coati.results.options import parse_duration, parse_instant, synthesize_timestamps
from support.compare import as_json

FRAMEWORK = frameworks.parse("calliope-v0-7-0")


def results(**values: Any) -> Results:
    return Results(FRAMEWORK, "optimal", True, **values)


# -- keys and conditions ----------------------------------------------------------------------


def test_keys() -> None:
    assert join("north", "pv") == "north::pv"
    assert join("north", "pv", "power") == "north::pv::power"
    assert positions(3) == [0, 1, 2]


@pytest.mark.parametrize(
    "condition",
    ["optimal", "Optimal", "feasible", "locallyOptimal", "globally_optimal", "locally optimal"],
)
def test_conditions_of_a_model_with_a_solution(condition: str) -> None:
    assert succeeded(condition)


@pytest.mark.parametrize(
    "condition",
    ["infeasible", "unbounded", "maxTimeLimit", "unknown", "not_solved", "", "suboptimal", "error"],
)
def test_conditions_of_a_model_without_a_solution(condition: str) -> None:
    assert not succeeded(condition)


# -- flows between locations ------------------------------------------------------------------


def test_flows_are_netted_for_each_pair() -> None:
    flows = net_flows(
        {
            ("north", "south"): np.array([3.0, 0.0]),
            ("south", "north"): np.array([1.0, 2.0]),
            ("west", "east"): np.array([5.0, 5.0]),
        }
    )
    assert list(flows) == ["east::west", "north::south"]
    assert flows["north::south"].origin == "north"
    assert flows["north::south"].destination == "south"
    assert flows["north::south"].timeseries.tolist() == [2.0, -2.0]
    assert flows["east::west"].timeseries.tolist() == [-5.0, -5.0]


def test_pairs_that_exchange_nothing_are_left_out() -> None:
    flows = net_flows(
        {
            ("a", "b"): np.array([0.0, INACTIVE / 2]),
            ("c", "d"): np.array([0.0, INACTIVE]),
            ("e", "f"): np.array([1.0, 0.0]),
            ("f", "e"): np.array([1.0, 0.0]),
            ("g", "g"): np.array([9.0, 9.0]),
            ("h", "i"): np.array([]),
        }
    )
    assert list(flows) == ["c::d"]


def test_a_flow_without_a_value_is_no_flow() -> None:
    flows = net_flows({("a", "b"): np.array([np.nan, 2.0])})
    assert flows["a::b"].timeseries.tolist() == [0.0, 2.0]


def test_an_exchange_as_it_is_written() -> None:
    exchange = Transmission("a", "b", np.array([1.0]))
    assert as_json(exchange.to_document()) == {"from": "a", "to": "b", "timeseries": [1.0]}


# -- the document -----------------------------------------------------------------------------


def test_the_least_that_a_document_holds() -> None:
    document = as_json(results().to_document())
    assert document == {
        "schema_version": "1.0",
        "framework": "calliope",
        "framework_version": "0.7.0",
        "model_name": None,
        "solver": None,
        "success": True,
        "termination_condition": "optimal",
        "objective": None,
        "timestamps": [],
        "capacities": {},
        "generation": {},
        "dispatch": {},
        "demand_timeseries": [],
        "transmission_flow": {},
        "costs_by_tech": {},
        "costs_by_location": {},
        "tech_metadata": {},
        "tech_parents": {},
        "warnings": [],
        "metadata": {
            "generator": "coati",
            "generator_version": coati.__version__,
            "framework_id": "calliope-v0-7-0",
            "framework_family": "calliope-v0-7",
            "source": {},
        },
    }


def test_the_order_of_the_keys() -> None:
    found = results(
        objective_function_value=1.0,
        weights=np.array([1.0, 2.0]),
        periods=[2030, 2040],
        scenarios={"a": 1.0},
        storage_capacities={"a::b": 1.0},
        demand_by_location={"a": 1.0},
        unmet_demand_timeseries=np.array([1.0, 0.0]),
        unmet_demand_by_location={"a": 1.0},
        transmission_flow={"a::b": Transmission("a", "b", np.array([1.0, -1.0]))},
        coordinates={"a": [1.0, 2.0]},
        details={"mode": "base"},
    )
    assert list(found.to_document({"name": "x"})) == [
        "schema_version",
        "framework",
        "framework_version",
        "model_name",
        "solver",
        "success",
        "termination_condition",
        "objective",
        "objective_function_value",
        "timestamps",
        "weights",
        "periods",
        "scenarios",
        "capacities",
        "storage_capacities",
        "generation",
        "dispatch",
        "demand_timeseries",
        "demand_by_location",
        "unmet_demand_timeseries",
        "unmet_demand_by_location",
        "total_unmet_demand",
        "transmission_flow",
        "imports_by_location",
        "exports_by_location",
        "costs_by_tech",
        "costs_by_location",
        "tech_metadata",
        "tech_parents",
        "coordinates",
        "details",
        "warnings",
        "metadata",
    ]


def test_weights_that_are_all_one_are_left_out() -> None:
    assert "weights" not in results(weights=np.ones(3)).to_document()
    assert "weights" not in results(weights=np.array([])).to_document()
    assert "weights" in results(weights=np.array([1.0, 0.5])).to_document()


def test_unmet_demand_is_reported_if_there_is_any() -> None:
    nothing = results(unmet_demand_timeseries=np.zeros(3), unmet_demand_by_location={})
    assert "unmet_demand_timeseries" not in nothing.to_document()
    assert "total_unmet_demand" not in nothing.to_document()
    some = results(unmet_demand_timeseries=np.array([0.0, 2.0]), weights=np.array([1.0, 3.0]))
    assert some.to_document()["total_unmet_demand"] == 6.0


def test_totals_count_each_time_with_its_weight() -> None:
    weighted = results(weights=np.array([1.0, 3.0]))
    assert weighted.total(np.array([2.0, 2.0])) == 8.0
    assert weighted.total(np.array([2.0, np.nan])) == 2.0
    assert weighted.total(np.array([1.0, 1.0, 1.0])) == 3.0
    assert results().total(np.array([2.0, 2.0])) == 4.0


def test_exchanges() -> None:
    found = results(
        weights=np.array([1.0, 2.0]),
        transmission_flow={
            "a::b": Transmission("a", "b", np.array([4.0, -1.0])),
            "b::c": Transmission("b", "c", np.array([3.0, 3.0])),
        },
    )
    imports, exports = found.exchanges()
    assert imports == {"b": 4.0, "a": 2.0, "c": 9.0}
    assert exports == {"a": 4.0, "b": 2.0 + 9.0}


def test_costs() -> None:
    found = results()
    found.add_cost("a", "pv", 10.0)
    found.add_cost("a", "pv", 5.0)
    found.add_cost("b", "pv", 1.0)
    found.add_cost("b", "export", -4.0)
    found.add_cost("b", "idle", 0.0)
    found.add_cost("b", "unknown", float("nan"))
    found.finish()
    assert found.costs_by_location == {
        "a": {"pv": 15.0},
        "b": {"pv": 1.0, "export": -4.0, "idle": 0.0},
    }
    assert found.costs_by_tech == {"pv": 16.0}


def test_dispatch() -> None:
    found = results()
    found.add_dispatch("pv", np.array([1.0, np.nan]))
    found.add_dispatch("pv", np.array([2.0, 3.0]))
    found.add_dispatch("idle", np.array([0.0, 0.0]))
    found.add_dispatch("load", np.array([-1.0, -1.0]))
    found.finish()
    assert {name: series.tolist() for name, series in found.dispatch.items()} == {"pv": [3.0, 3.0]}


def test_the_kinds_of_the_technologies_are_listed_twice() -> None:
    found = results(tech_metadata={"pv": {"parent": "supply", "carrier_out": "power"}, "x": {}})
    assert found.to_document()["tech_parents"] == {"pv": "supply", "x": ""}


def test_a_framework_without_a_family_cannot_be_read() -> None:
    with pytest.raises(FrameworkError, match="Calliope: the version is needed to read the file"):
        extract_results(None, frameworks.parse("calliope"))  # type: ignore[arg-type]


# -- the choices of the caller ----------------------------------------------------------------


def test_the_defaults() -> None:
    assert ExtractOptions() == ExtractOptions(True, None, None, None)


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("1h", 3600),
        ("1 h", 3600),
        ("2hours", 7200),
        ("0.5h", 1800),
        ("30min", 1800),
        ("15 minutes", 900),
        ("15T", 900),
        ("90s", 90),
        ("1d", 86400),
        ("7 days", 7 * 86400),
        ("1H", 3600),
        ("0.25s", 0.25),
    ],
)
def test_durations(text: str, seconds: float) -> None:
    assert parse_duration(text) == round(seconds * 1_000_000)


@pytest.mark.parametrize(
    "text", ["", "h", "1", "1 month", "1y", "-1h", "0h", "1h30min", "one hour"]
)
def test_what_is_no_duration(text: str) -> None:
    with pytest.raises(CoatiError, match=r"is not a duration|must be longer than zero"):
        parse_duration(text)


@pytest.mark.parametrize(
    ("text", "instant"),
    [
        ("2025-01-01", "2025-01-01T00:00:00"),
        ("2025-01-01T06:30", "2025-01-01T06:30:00"),
        ("2025-01-01 06:30:15", "2025-01-01T06:30:15"),
        (" 2025-01-01T06:30:15.5 ", "2025-01-01T06:30:15.500000"),
    ],
)
def test_instants(text: str, instant: str) -> None:
    assert parse_instant(text) == np.datetime64(instant, "us")


@pytest.mark.parametrize("text", ["", "yesterday", "2025-13-01", "2025-02-30", "01.01.2025", "NaT"])
def test_what_is_no_instant(text: str) -> None:
    with pytest.raises(CoatiError, match="is not a time"):
        parse_instant(text)


def test_timestamps_made_from_a_start_and_a_step() -> None:
    options = ExtractOptions(time_start="2025-01-01T22:00", time_step="90min")
    assert as_json(synthesize_timestamps(options, 3)) == [
        "2025-01-01T22:00:00",
        "2025-01-01T23:30:00",
        "2025-01-02T01:00:00",
    ]
    assert as_json(synthesize_timestamps(options, 0)) == []
    assert synthesize_timestamps(ExtractOptions(), 3) == [0, 1, 2]


@pytest.mark.parametrize(
    "options",
    [
        {"time_start": "2025-01-01"},
        {"time_step": "1h"},
        {"time_start": "soon", "time_step": "1h"},
        {"time_start": "2025-01-01", "time_step": "a while"},
    ],
)
def test_choices_that_make_no_sense_are_refused(options: dict) -> None:
    with pytest.raises(CoatiError):
        ExtractOptions(**options)
