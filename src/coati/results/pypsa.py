"""Results of PyPSA.

A PyPSA network consists of components attached to buses. The results document
speaks of technologies at locations instead, so the extractor translates:

* The **location** of a component is that of its bus. A bus named
  `north::electricity` is at the location `north` and carries
  `electricity`; any other bus is its own location and carries what its
  attribute `carrier` says.
* The **technology** is the name of the component, without the location if the
  name states it as `north::pv` or `pv@north`.
* The **kind** of the technology follows from the kind of the component:

    | Component | Kind |
    |---|---|
    | `Generator` | `supply` |
    | `Load` | `demand` |
    | `StorageUnit`, `Store` | `storage` |
    | `Link` | `transmission` or `conversion` |
    | `Line`, `Transformer` | `transmission` |

  A link is a transmission if it joins two locations on one carrier and has
  no further outputs.

A component that joins two locations is a connection between them. Its
capacity is listed at both ends, and each end bears half of its cost.

Costs follow the definitions of `n.statistics`: the capital cost of a
component is its `capital_cost` times its optimised capacity, whether or not
the capacity was extendable, and the operational cost is its `marginal_cost`
times its dispatch, weighted with the objective weighting of the snapshots.
The `objective` of the document is the sum of these costs. The objective of
the network, which the document reports as `objective_function_value`, is
another number: PyPSA leaves out of it the capital cost of the capacities that
were given, and counts in it what the generators cost that stand for demand
that is not met. `details` names these parts, so that the two can be
reconciled:

```text
objective_function_value + objective_constant
    = objective - capital_cost_of_given_capacities + cost_of_unmet_demand
```

A stochastic network holds one set of results for each scenario. The document
reports their expectation, the sum weighted with the probabilities of the
scenarios, which is also what the objective of the network is.

PyPSA does not record how the solver ended. A network that has an objective has
been optimised, and PyPSA assigns a solution only if the solver found the
optimum, so the termination condition of such a network is reported as
`optimal`; that of any other as `not_solved`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Final

import numpy as np

from coati.frameworks import Framework
from coati.labeled import finite
from coati.model import Dataset
from coati.results.document import SEPARATOR, Results, join, net_flows
from coati.results.options import ExtractOptions, synthesize_timestamps
from coati.results.pypsa_network import Component, Network, read_network

__all__ = ["extract"]

_SUPPLY: Final = "supply"
_DEMAND: Final = "demand"
_STORAGE: Final = "storage"
_CONVERSION: Final = "conversion"
_TRANSMISSION: Final = "transmission"

# Generators that stand for demand the system fails to meet, by carrier or technology.
_SHORTFALL: Final = frozenset({"unmet_demand", "load_shedding", "load shedding"})

# The coordinate reference system in which x is the longitude and y the latitude.
_WGS84: Final = 4326

# Costs that PyPSA knows and the document does not count, with the tables that may state them.
_UNCOUNTED: Final = (
    "marginal_cost_quadratic",
    "marginal_cost_storage",
    "spill_cost",
    "stand_by_cost",
    "start_up_cost",
    "shut_down_cost",
)
_TABLES: Final = ("generators", "storage_units", "stores", "links", "lines", "transformers")

# How far the objective may be from the costs that make it up, relative and absolute.
_CLOSE: Final = (1e-4, 1e-3)

_Arrivals = dict[tuple[str, str], np.ndarray[Any, Any]]


@dataclass
class _Costs:
    """What the components of one kind cost.

    Attributes:
        capital: The cost of the capacity of each component.
        running: The cost of the operation of each component.
        decided: Whether the capacity of each component was decided by the
            optimisation, not given.
    """

    capital: np.ndarray[Any, Any]
    running: np.ndarray[Any, Any]
    decided: np.ndarray[Any, Any]

    def of(self, position: int) -> float:
        """Return what a component costs."""
        return float(self.capital[position] + self.running[position])

    def given(self, position: int) -> float:
        """Return the part of the cost that the objective of PyPSA leaves out."""
        return 0.0 if self.decided[position] else float(self.capital[position])


def extract(dataset: Dataset, framework: Framework, options: ExtractOptions) -> Results:
    """Make the results of a file of PyPSA.

    Raises:
        ExtractionError: The file does not hold the tables of a network.
    """
    networks = read_network(dataset)
    first = networks[0]
    solved = first.objective is not None
    results = Results(framework, "optimal" if solved else "not_solved", solved)
    results.model_name = first.name
    results.objective_function_value = first.objective
    results.timestamps = _timestamps(first, options)
    results.weights = first.weighting("generators")
    results.periods = first.periods
    if first.objective_constant is not None:
        results.details["objective_constant"] = first.objective_constant
    if not solved:
        results.warnings.append(
            "the network has no objective: it has not been optimised,"
            " and the capacities are those given, not decided"
        )
    parts = [_Scenario(network, framework, _geographic(dataset)).run() for network in networks]
    given, unmet = _blend(results, parts, first.scenarios)
    results.finish()
    if solved:
        _account(results, first, given, unmet)
    return results


def _account(results: Results, network: Network, given: float, unmet: float) -> None:
    """Set the cost of the system and say how it relates to the objective of the network.

    Args:
        results: The results, with the costs of all technologies.
        network: The network, or the first scenario of it.
        given: The capital cost of the capacities that were given, not decided.
        unmet: The cost of the generators that stand for demand that is not met.
    """
    total = math.fsum(
        cost for costs in results.costs_by_location.values() for cost in costs.values()
    )
    results.objective = total
    if given:
        results.details["capital_cost_of_given_capacities"] = given
    if unmet:
        results.details["cost_of_unmet_demand"] = unmet
    uncounted = [
        f"{attribute} of the {table}"
        for table in _TABLES
        for attribute in _UNCOUNTED
        if _states(network.component(table), attribute)
    ]
    if uncounted:
        results.warnings.append(
            "the network states costs that the document does not count: " + ", ".join(uncounted)
        )
        return
    if network.periods or network.objective is None:
        return
    stated = network.objective + (network.objective_constant or 0.0)
    counted = total - given + unmet
    relative, absolute = _CLOSE
    if not math.isclose(counted, stated, rel_tol=relative, abs_tol=absolute):
        results.warnings.append(
            f"the objective of the network and its constant add up to {stated:.10g}, the costs"
            f" that the document counts towards them to {counted:.10g}; the network may have"
            " been optimised with an objective of its own, or in several steps"
        )


def _states(component: Component, attribute: str) -> bool:
    """Tell whether any component states the attribute with a value other than zero."""
    for stored in (component.static.get(attribute), component.series.get(attribute)):
        if stored is not None and stored.dtype.kind in "biuf" and np.any(finite(stored) != 0):
            return True
    return False


def _geographic(dataset: Dataset) -> bool:
    """Tell whether the coordinates of the buses are longitudes and latitudes."""
    system = dataset.attributes.get("network_srid", _WGS84)
    return not isinstance(system, (int, float)) or int(system) == _WGS84


def _timestamps(network: Network, options: ExtractOptions) -> Any:
    labels = network.timestamps
    if options.time_start is not None and not any(isinstance(label, str) for label in labels):
        return synthesize_timestamps(options, len(labels))
    return labels


class _Scenario:
    """Translates one network, or one scenario of a stochastic network."""

    def __init__(self, network: Network, framework: Framework, geographic: bool) -> None:
        self._network = network
        self._geographic = geographic
        self._length = network.snapshots
        self._energy = network.weighting("generators")
        self._money = network.weighting("objective")
        self._solved = network.objective is not None
        self._location: dict[str, str] = {}
        self._carrier: dict[str, str] = {}
        self._arrivals: _Arrivals = {}
        self.results = Results(framework, "", False)
        self.arrivals = self._arrivals
        self.given = 0.0
        self.unmet = 0.0

    def run(self) -> _Scenario:
        self._buses()
        self._generators()
        self._storage_units()
        self._stores()
        self._loads()
        self._links()
        for table in ("lines", "transformers"):
            self._branches(table)
        return self

    # -- naming -----------------------------------------------------------------------------

    def _buses(self) -> None:
        buses = self._network.component("buses")
        carriers = buses.texts("carrier")
        for name, carrier in zip(buses.names, carriers, strict=True):
            location, _, rest = name.partition(SEPARATOR)
            self._location[name] = location
            self._carrier[name] = carrier or rest or "AC"
        if not self._geographic or not (buses.has("x") or buses.has("y")):
            return
        east, north = buses.numbers("x", 0.0), buses.numbers("y", 0.0)
        for position, name in enumerate(buses.names):
            self.results.coordinates.setdefault(
                self._location[name], [float(north[position]), float(east[position])]
            )

    def _place(self, bus: str) -> tuple[str, str]:
        """Return the location and the carrier of a bus."""
        location = self._location.get(bus)
        if location is None:
            location, _, rest = bus.partition(SEPARATOR)
            return location, rest or "AC"
        return location, self._carrier[bus]

    @staticmethod
    def _technology(name: str, location: str) -> str:
        """Return the name of a component without the location it may state."""
        if location and name.startswith(location + SEPARATOR):
            return name[len(location) + len(SEPARATOR) :]
        if location and name.endswith("@" + location):
            return name[: -len(location) - 1]
        return name

    def _capacity(self, component: Component, attribute: str) -> np.ndarray[Any, Any]:
        """Return the capacity: the optimised one of a network that has been optimised."""
        given = component.numbers(attribute, 0.0)
        if not self._solved:
            return given
        if not component.has(attribute + "_opt"):
            return np.zeros(len(component))
        return component.numbers(attribute + "_opt", 0.0)

    def _costs(
        self,
        component: Component,
        attribute: str,
        capacity: np.ndarray[Any, Any],
        dispatch: np.ndarray[Any, Any] | None,
    ) -> _Costs:
        """Return what the components cost: their capacity and their operation."""
        capital = component.numbers("capital_cost", 0.0) * capacity
        running = np.zeros(len(component))
        if dispatch is not None:
            price = component.varying("marginal_cost", 0.0, self._length)
            running = (price * dispatch * self._money[:, np.newaxis]).sum(axis=0)
        decided = component.numbers(attribute + "_extendable", 0.0) > 0
        return _Costs(np.asarray(capital), np.asarray(running), decided)

    def _charge(
        self, location: str, technology: str, costs: _Costs, position: int, share: float = 1.0
    ) -> None:
        """Record the cost of a component; a network that has not been optimised has none."""
        if self._solved:
            self.results.add_cost(location, technology, share * costs.of(position))
            self.given += share * costs.given(position)

    def _connect(
        self,
        technology: str,
        ends: tuple[str, str],
        capacity: float,
        costs: _Costs,
        position: int,
    ) -> None:
        """Record the capacity of a connection at both of its ends, which share its cost."""
        places = ends[:1] if ends[0] == ends[1] else ends
        for place in places:
            self._add(self.results.capacities, join(place, technology), capacity)
            self._charge(place, technology, costs, position, 1 / len(places))

    def _register(self, technology: str, kind: str, carrier: str) -> None:
        self.results.tech_metadata.setdefault(technology, {"parent": kind, "carrier_out": carrier})

    def _add(self, target: dict[str, float], key: str, value: float) -> None:
        target[key] = target.get(key, 0.0) + float(value)

    def _deliver(
        self, technology: str, location: str, carrier: str, out: np.ndarray[Any, Any]
    ) -> None:
        """Record what a technology puts out at a location."""
        energy = float((out * self._energy).sum())
        self._add(self.results.generation, join(location, technology, carrier), energy)

    def _arrive(self, origin: str, destination: str, arriving: np.ndarray[Any, Any]) -> None:
        known = self._arrivals.get((origin, destination))
        self._arrivals[origin, destination] = arriving if known is None else known + arriving

    # -- components -------------------------------------------------------------------------

    def _generators(self) -> None:
        generators = self._network.component("generators")
        output = generators.flow("p", self._length)
        capacity = self._capacity(generators, "p_nom")
        costs = self._costs(generators, "p_nom", capacity, output)
        carriers = generators.texts("carrier")
        for position, (name, bus) in enumerate(
            zip(generators.names, generators.texts("bus"), strict=True)
        ):
            location, carrier = self._place(bus)
            technology = self._technology(name, location)
            series = output[:, position]
            if {carriers[position].lower(), technology.lower()} & _SHORTFALL:
                self._shortfall(location, series)
                if self._solved:
                    self.unmet += costs.of(position) - costs.given(position)
                continue
            self._add(self.results.capacities, join(location, technology), capacity[position])
            self._deliver(technology, location, carrier, series)
            self.results.add_dispatch(technology, series)
            self._charge(location, technology, costs, position)
            self._register(technology, _SUPPLY, carrier)

    def _shortfall(self, location: str, series: np.ndarray[Any, Any]) -> None:
        unmet = np.maximum(series, 0.0)
        known = self.results.unmet_demand_timeseries
        self.results.unmet_demand_timeseries = unmet if known is None else known + unmet
        energy = float((unmet * self._energy).sum())
        if energy > 0:
            self._add(self.results.unmet_demand_by_location, location, energy)

    def _storage_units(self) -> None:
        units = self._network.component("storage_units")
        discharge = np.maximum(units.flow("p", self._length), 0.0)
        capacity = self._capacity(units, "p_nom")
        hours = units.numbers("max_hours", 1.0)
        costs = self._costs(units, "p_nom", capacity, discharge)
        for position, (name, bus) in enumerate(zip(units.names, units.texts("bus"), strict=True)):
            location, carrier = self._place(bus)
            technology = self._technology(name, location)
            key = join(location, technology)
            self._add(self.results.capacities, key, capacity[position])
            self._add(self.results.storage_capacities, key, capacity[position] * hours[position])
            self._deliver(technology, location, carrier, discharge[:, position])
            self.results.add_dispatch(technology, discharge[:, position])
            self._charge(location, technology, costs, position)
            self._register(technology, _STORAGE, carrier)

    def _stores(self) -> None:
        stores = self._network.component("stores")
        flow = stores.flow("p", self._length)
        withdrawal = np.maximum(flow, 0.0)
        capacity = self._capacity(stores, "e_nom")
        costs = self._costs(stores, "e_nom", capacity, flow)
        for position, (name, bus) in enumerate(zip(stores.names, stores.texts("bus"), strict=True)):
            location, carrier = self._place(bus)
            technology = self._technology(name, location)
            key = join(location, technology)
            self._add(self.results.storage_capacities, key, capacity[position])
            self._deliver(technology, location, carrier, withdrawal[:, position])
            self.results.add_dispatch(technology, withdrawal[:, position])
            self._charge(location, technology, costs, position)
            self._register(technology, _STORAGE, carrier)

    def _loads(self) -> None:
        loads = self._network.component("loads")
        if not len(loads):
            return
        if "p" in loads.series:
            consumed = np.abs(loads.flow("p", self._length))
        else:
            consumed = np.abs(loads.varying("p_set", 0.0, self._length))
        self.results.demand_timeseries = consumed.sum(axis=1)
        energy = (consumed * self._energy[:, np.newaxis]).sum(axis=0)
        for position, (name, bus) in enumerate(zip(loads.names, loads.texts("bus"), strict=True)):
            location, _ = self._place(bus)
            if energy[position] > 0:
                self._add(self.results.demand_by_location, location, energy[position])
            self._register(self._technology(name, location), _DEMAND, "")

    def _links(self) -> None:
        links = self._network.component("links")
        ports = sorted(
            int(name[3:]) for name in links.static if name.startswith("bus") and name[3:].isdigit()
        )
        buses = {port: links.texts(f"bus{port}") for port in ports}
        flows = {port: links.flow(f"p{port}", self._length) for port in ports}
        capacity = self._capacity(links, "p_nom")
        efficiency = links.numbers("efficiency", 1.0)
        costs = self._costs(links, "p_nom", capacity, flows.get(0))
        for position, name in enumerate(links.names):
            ends = [(port, buses[port][position]) for port in ports if buses[port][position]]
            outputs = [(port, bus) for port, bus in ends if port > 0]
            if not ends or ends[0][0] != 0 or not outputs:
                continue
            origin, carrier = self._place(ends[0][1])
            destination, delivered = self._place(outputs[0][1])
            crossing = len(outputs) == 1 and origin != destination and carrier == delivered
            if crossing:
                technology = self._technology(name, origin)
                self._connect(
                    technology, (origin, destination), capacity[position], costs, position
                )
                self._exchange(technology, carrier, origin, destination, flows, position)
                continue
            technology = self._technology(name, destination)
            rated = capacity[position] * efficiency[position]
            self._add(self.results.capacities, join(destination, technology), rated)
            self._charge(destination, technology, costs, position)
            self._register(technology, _CONVERSION, delivered)
            for port, bus in outputs:
                location, carrier = self._place(bus)
                out = np.maximum(-flows[port][:, position], 0.0)
                self._deliver(technology, location, carrier, out)
                self.results.add_dispatch(technology, out)

    def _exchange(
        self,
        technology: str,
        carrier: str,
        origin: str,
        destination: str,
        flows: dict[int, np.ndarray[Any, Any]],
        position: int,
    ) -> None:
        """Record what a link or a branch carries between two locations."""
        self._register(technology, _TRANSMISSION, carrier)
        for port, source, target in ((1, origin, destination), (0, destination, origin)):
            if port not in flows:
                continue
            arriving = np.maximum(-flows[port][:, position], 0.0)
            self._arrive(source, target, arriving)
            self._deliver(technology, target, carrier, arriving)

    def _branches(self, table: str) -> None:
        branches = self._network.component(table)
        capacity = self._capacity(branches, "s_nom")
        costs = self._costs(branches, "s_nom", capacity, None)
        flows = {port: branches.flow(f"p{port}", self._length) for port in (0, 1)}
        first, second = branches.texts("bus0"), branches.texts("bus1")
        for position, name in enumerate(branches.names):
            origin, carrier = self._place(first[position])
            destination, _ = self._place(second[position])
            technology = self._technology(name, origin)
            self._connect(technology, (origin, destination), capacity[position], costs, position)
            self._register(technology, _TRANSMISSION, carrier)
            if origin != destination:
                self._exchange(technology, carrier, origin, destination, flows, position)


def _blend(
    results: Results, parts: list[_Scenario], scenarios: dict[str, float] | None
) -> tuple[float, float]:
    """Fill `results` with the expectation of the scenarios.

    Returns:
        The expectation of two costs that tell the objective of the network
        from the cost of the system: the capital cost of the capacities that
        were given, and the cost of the demand that is not met.
    """
    weights = list((scenarios or {}).values()) or [1.0]
    total = sum(weights) or 1.0
    shares = [weight / total for weight in weights]
    if scenarios is not None:
        results.scenarios = dict(zip(scenarios, shares, strict=True))
        results.warnings.append(
            f"the network has {len(scenarios)} scenarios; the document reports the expectation"
        )
    arrivals: _Arrivals = {}
    for share, part in zip(shares, parts, strict=True):
        found = part.results
        for name in (
            "capacities",
            "storage_capacities",
            "generation",
            "demand_by_location",
            "unmet_demand_by_location",
        ):
            target = getattr(results, name)
            for key, value in getattr(found, name).items():
                target[key] = target.get(key, 0.0) + share * value
        for location, costs in found.costs_by_location.items():
            for technology, cost in costs.items():
                results.add_cost(location, technology, share * cost)
        for technology, series in found.dispatch.items():
            results.add_dispatch(technology, share * series)
        for name in ("demand_timeseries", "unmet_demand_timeseries"):
            series = getattr(found, name)
            if series is not None:
                known = getattr(results, name)
                setattr(results, name, share * series if known is None else known + share * series)
        for pair, arriving in part.arrivals.items():
            known = arrivals.get(pair)
            arrivals[pair] = share * arriving if known is None else known + share * arriving
        for technology, entry in found.tech_metadata.items():
            results.tech_metadata.setdefault(technology, entry)
        for location, place in found.coordinates.items():
            results.coordinates.setdefault(location, place)
    results.transmission_flow = net_flows(arrivals)
    given = math.fsum(share * part.given for share, part in zip(shares, parts, strict=True))
    unmet = math.fsum(share * part.unmet for share, part in zip(shares, parts, strict=True))
    return given, unmet
