"""The results document: what a solved model says, the same for every framework.

An extractor reads the file of one framework and fills a `Results`
object; `Results.to_document` turns it into the dictionary that is
written as JSON. The keys of the document and their meaning are described in
the documentation under *Results document*; `coati schema results` prints the
JSON Schema.

Locations, technologies and carriers are joined into keys with `::`, as in
`region1::ccgt::power`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

import numpy as np

from coati._version import __version__
from coati.frameworks import Framework

__all__ = [
    "INACTIVE",
    "SCHEMA_VERSION",
    "SEPARATOR",
    "SOLVED",
    "Results",
    "Transmission",
    "join",
    "net_flows",
    "positions",
    "solutions_of_spores",
    "succeeded",
]

#: The version of the layout of the results document.
SCHEMA_VERSION: Final = "1.0"

#: What joins a location, a technology and a carrier into a key.
SEPARATOR: Final = "::"

#: A flow that stays below this magnitude at every time is not reported.
INACTIVE: Final = 1e-6

#: The termination conditions, in lower case, of a model that has a solution.
SOLVED: Final = frozenset({"optimal", "feasible", "locallyoptimal", "globallyoptimal"})


def join(*parts: str) -> str:
    """Join a location, a technology and, if given, a carrier into a key."""
    return SEPARATOR.join(parts)


def succeeded(termination_condition: str) -> bool:
    """Tell whether `termination_condition` is that of a model with a solution."""
    return termination_condition.replace("_", "").replace(" ", "").lower() in SOLVED


def positions(length: int) -> list[int]:
    """Return the timestamps of a model whose file records no times: the positions."""
    return list(range(length))


def solutions_of_spores(count: int) -> str:
    """Return the warning about a file that holds the solutions of the SPORES mode."""
    held = "one solution" if count == 1 else f"{count} solutions"
    return (
        f"the file holds {held} of the SPORES mode; the document reports the first,"
        " details.spores lists the cost, the capacities and the generation of each"
    )


@dataclass
class Transmission:
    """The exchange between two locations.

    Attributes:
        origin: The location the flow is counted from, the first of the two
            in the order of their names.
        destination: The other location.
        timeseries: The net flow that arrives at `destination` from
            `origin` at each time, negative in the opposite direction.
    """

    origin: str
    destination: str
    timeseries: np.ndarray[Any, Any]

    def to_document(self) -> dict[str, Any]:
        """Return the exchange as it is written to the document."""
        return {"from": self.origin, "to": self.destination, "timeseries": self.timeseries}


def net_flows(
    arrivals: dict[tuple[str, str], np.ndarray[Any, Any]],
) -> dict[str, Transmission]:
    """Net the flows between locations into one exchange for each pair.

    Args:
        arrivals: For a pair of locations `(origin, destination)`, what
            arrives at `destination` from `origin` at each time.

    Returns:
        The exchanges by the key `a::b`, where `a` precedes `b` in the
        order of their names, without the pairs that exchange nothing.
    """
    net: dict[tuple[str, str], np.ndarray[Any, Any]] = {}
    for (origin, destination), arriving in arrivals.items():
        if origin == destination:
            continue
        first, second = sorted((origin, destination))
        signed = np.nan_to_num(np.asarray(arriving, dtype=np.float64))
        if destination == first:
            signed = -signed
        net[first, second] = net[first, second] + signed if (first, second) in net else signed
    return {
        join(first, second): Transmission(first, second, flow)
        for (first, second), flow in sorted(net.items())
        if flow.size and float(np.abs(flow).max()) >= INACTIVE
    }


@dataclass
class Results:
    """What a solved model says.

    Attributes:
        framework: The framework that wrote the file.
        termination_condition: How the solver ended, in the words of the framework.
        success: Whether the model has a solution.
        model_name: The name of the model, if the file records one.
        solver: The solver, if the file records it.
        objective: The cost of the system.
        objective_function_value: The value of the objective function, which
            may include penalties and weights that are no cost.
        timestamps: The times of the time series: instants, or positions if
            the file records no times.
        weights: How much each time counts towards a total, for a model in
            which the times stand for periods of different length or number.
            The totals of the document are weighted with it, the time series
            are not.
        periods: The investment period of each time, for a model with several.
        capacities: The capacity of each technology at each location.
        storage_capacities: The capacity of each store to hold energy.
        generation: What each technology puts out over the modelled time, for
            each location and carrier.
        dispatch: What each technology puts out at each time, all locations
            and carriers together.
        demand_timeseries: The demand at each time, all locations together.
        demand_by_location: The demand over the modelled time at each location.
        unmet_demand_timeseries: The demand that is not met at each time.
        unmet_demand_by_location: The demand that is not met, at each location.
        transmission_flow: The exchange between each pair of locations.
        costs_by_tech: The cost of each technology.
        costs_by_location: The cost of each technology at each location.
        tech_metadata: The kind of each technology and what it puts out.
        coordinates: The latitude and longitude of each location.
        scenarios: The weight of each scenario, for a stochastic model.
        details: What else the file says, in the terms of the framework.
        warnings: What a reader of the document should know about its making.
    """

    framework: Framework
    termination_condition: str
    success: bool
    model_name: str | None = None
    solver: str | None = None
    objective: float | None = None
    objective_function_value: float | None = None
    timestamps: Any = field(default_factory=list)
    weights: np.ndarray[Any, Any] | None = None
    periods: list[Any] | None = None
    capacities: dict[str, float] = field(default_factory=dict)
    storage_capacities: dict[str, float] = field(default_factory=dict)
    generation: dict[str, float] = field(default_factory=dict)
    dispatch: dict[str, np.ndarray[Any, Any]] = field(default_factory=dict)
    demand_timeseries: np.ndarray[Any, Any] | None = None
    demand_by_location: dict[str, float] = field(default_factory=dict)
    unmet_demand_timeseries: np.ndarray[Any, Any] | None = None
    unmet_demand_by_location: dict[str, float] = field(default_factory=dict)
    transmission_flow: dict[str, Transmission] = field(default_factory=dict)
    costs_by_tech: dict[str, float] = field(default_factory=dict)
    costs_by_location: dict[str, dict[str, float]] = field(default_factory=dict)
    tech_metadata: dict[str, dict[str, str]] = field(default_factory=dict)
    coordinates: dict[str, list[float]] = field(default_factory=dict)
    scenarios: dict[str, float] | None = None
    details: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def add_cost(self, location: str, technology: str, cost: float) -> None:
        """Add `cost` to what `technology` costs at `location`; `NaN` adds nothing."""
        if np.isnan(cost):
            return
        at_location = self.costs_by_location.setdefault(location, {})
        at_location[technology] = at_location.get(technology, 0.0) + cost

    def add_dispatch(self, technology: str, series: np.ndarray[Any, Any]) -> None:
        """Add `series` to what `technology` puts out at each time."""
        clean = np.nan_to_num(np.asarray(series, dtype=np.float64))
        known = self.dispatch.get(technology)
        self.dispatch[technology] = clean if known is None else known + clean

    def finish(self) -> None:
        """Derive what follows from the rest: the cost of each technology, and tidy up.

        A technology that puts out nothing at all is dropped from the
        dispatch, and `costs_by_tech` lists the technologies that cost
        something; `costs_by_location` keeps every entry.
        """
        totals: dict[str, float] = {}
        for at_location in self.costs_by_location.values():
            for technology, cost in at_location.items():
                totals[technology] = totals.get(technology, 0.0) + cost
        self.costs_by_tech = {name: cost for name, cost in totals.items() if cost > 0}
        self.dispatch = {
            name: series for name, series in self.dispatch.items() if float(series.sum()) > 0
        }

    def total(self, series: np.ndarray[Any, Any]) -> float:
        """Add up a time series, each time counted with its weight."""
        if self.weights is not None and self.weights.shape == series.shape:
            return float(np.nansum(series * self.weights))
        return float(np.nansum(series))

    def exchanges(self) -> tuple[dict[str, float], dict[str, float]]:
        """Return what each location takes in and gives away through transmission."""
        imports: dict[str, float] = {}
        exports: dict[str, float] = {}
        for exchange in self.transmission_flow.values():
            forward = self.total(np.maximum(exchange.timeseries, 0.0))
            backward = self.total(np.maximum(-exchange.timeseries, 0.0))
            for location, taken, given in (
                (exchange.destination, forward, backward),
                (exchange.origin, backward, forward),
            ):
                imports[location] = imports.get(location, 0.0) + taken
                exports[location] = exports.get(location, 0.0) + given
        return (
            {name: value for name, value in imports.items() if value > 0},
            {name: value for name, value in exports.items() if value > 0},
        )

    def to_document(self, source: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return the dictionary that is written as JSON.

        Args:
            source: What is known about the file, reported under `metadata`.
        """
        document: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "framework": self.framework.name,
            "framework_version": self.framework.version,
            "model_name": self.model_name,
            "solver": self.solver,
            "success": self.success,
            "termination_condition": self.termination_condition,
            "objective": self.objective,
        }
        _put(document, "objective_function_value", self.objective_function_value)
        document["timestamps"] = self.timestamps
        if self.weights is not None and self.weights.size and np.any(self.weights != 1):
            document["weights"] = self.weights
        _put(document, "periods", self.periods)
        _put(document, "scenarios", self.scenarios)
        document["capacities"] = self.capacities
        _put(document, "storage_capacities", self.storage_capacities)
        document["generation"] = self.generation
        document["dispatch"] = self.dispatch
        document["demand_timeseries"] = _series(self.demand_timeseries)
        _put(document, "demand_by_location", self.demand_by_location)
        self._put_unmet_demand(document)
        document["transmission_flow"] = {
            key: exchange.to_document() for key, exchange in self.transmission_flow.items()
        }
        imports, exports = self.exchanges()
        _put(document, "imports_by_location", imports)
        _put(document, "exports_by_location", exports)
        document["costs_by_tech"] = self.costs_by_tech
        document["costs_by_location"] = self.costs_by_location
        document["tech_metadata"] = self.tech_metadata
        document["tech_parents"] = {
            name: entry.get("parent", "") for name, entry in self.tech_metadata.items()
        }
        _put(document, "coordinates", self.coordinates)
        _put(document, "details", self.details)
        document["warnings"] = self.warnings
        document["metadata"] = {
            "generator": "coati",
            "generator_version": __version__,
            "framework_id": self.framework.id,
            "framework_family": self.framework.family.id if self.framework.family else None,
            "source": source or {},
        }
        return document

    def _put_unmet_demand(self, document: dict[str, Any]) -> None:
        unmet = self.unmet_demand_timeseries
        if unmet is None or not unmet.size or float(np.nansum(unmet)) <= 0:
            return
        document["unmet_demand_timeseries"] = unmet
        document["unmet_demand_by_location"] = self.unmet_demand_by_location
        document["total_unmet_demand"] = self.total(unmet)


def _put(document: dict[str, Any], key: str, value: Any) -> None:
    """Add `value` under `key` unless it is `None` or empty."""
    if value is None or (isinstance(value, (dict, list)) and not value):
        return
    document[key] = value


def _series(series: np.ndarray[Any, Any] | None) -> Any:
    return [] if series is None else series
