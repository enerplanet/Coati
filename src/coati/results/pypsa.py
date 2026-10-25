"""Results of PyPSA.

A PyPSA network consists of components attached to buses. The results document
speaks of technologies at locations instead, so the extractor translates:

* The **location** of a component is that of its bus. A bus named
  `north::electricity` is at the location `north` and carries
  `electricity`, whatever its attribute `carrier` says, and a further part of
  the name, as in `north::electricity::battery`, tells the buses of a location
  and a carrier apart; any other bus is its own location and carries what its
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
times its dispatch, weighted with the objective weighting of the snapshots,
together with the other costs of operation that PyPSA knows: the quadratic
marginal cost, the cost of holding energy in a store, the cost of spilling,
and the costs of a committable unit for standing by, starting up and shutting
down. Each is counted from the time series that PyPSA writes for it.
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
`optimal`. A network without an objective whose buses have results holds the
solution of a power flow, which `coati.results.pypsa_power_flow` describes;
any other network is `not_solved`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Final

import numpy as np

from coati.frameworks import Framework
from coati.labeled import finite
from coati.model import Dataset
from coati.results import pypsa_power_flow
from coati.results.document import FIXED, SEPARATOR, VARIABLE, Results, join, net_flows
from coati.results.options import ExtractOptions, synthesize_timestamps
from coati.results.pypsa_network import Component, Network, read_network

__all__ = ["extract"]

_SUPPLY: Final = "supply"
_DEMAND: Final = "demand"
_STORAGE: Final = "storage"
_CONVERSION: Final = "conversion"
_TRANSMISSION: Final = "transmission"

# Generators that stand for demand the system fails to meet, by carrier or technology.
_SHORTFALL: Final = frozenset({"unmet", "unmet_demand", "load_shedding", "load shedding"})

# The coordinate reference system in which x is the longitude and y the latitude.
_WGS84: Final = 4326

# The costs of operation that PyPSA knows besides the marginal cost, by the table of the
# components: the attribute that prices them, the time series that they apply to, whether the
# series is squared, and whether the cost counts each snapshot with the objective weighting.
# (An event such as a start-up is counted once, a state such as standing by for as long as it
# lasts.) PyPSA writes a series only where a value differs from the default, so a series that
# the file lacks has the default: no start-up, no spill, and the status "on" of a unit that
# was never off (see `_amount`).
_Other = tuple[str, str, bool, bool]
_OTHER_COSTS: Final[dict[str, tuple[_Other, ...]]] = {
    "generators": (
        ("marginal_cost_quadratic", "p", True, True),
        ("stand_by_cost", "status", False, True),
        ("start_up_cost", "start_up", False, False),
        ("shut_down_cost", "shut_down", False, False),
    ),
    "storage_units": (
        ("marginal_cost_quadratic", "p_dispatch", True, True),
        ("marginal_cost_storage", "state_of_charge", False, True),
        ("spill_cost", "spill", False, True),
    ),
    "stores": (
        ("marginal_cost_quadratic", "p", True, True),
        ("marginal_cost_storage", "e", False, True),
    ),
    "links": (
        ("marginal_cost_quadratic", "p0", True, True),
        ("stand_by_cost", "status", False, True),
        ("start_up_cost", "start_up", False, False),
        ("shut_down_cost", "shut_down", False, False),
    ),
}

# How far the objective may be from the costs that make it up, relative and absolute.
_CLOSE: Final = (1e-4, 1e-3)

# The attribute of a carrier that states what burning a unit of it emits, which PyPSA counts
# towards a limit of the type primary_energy.
_INTENSITY: Final = "co2_emissions"

# The attributes of a global constraint that the document reports, with the defaults that PyPSA
# gives them and leaves out of a file; an attribute without a default is reported if stated.
_CONSTRAINT_TEXTS: Final = {
    "type": "primary_energy",
    "carrier_attribute": "co2_emissions",
    "sense": "<=",
}
_CONSTRAINT_NUMBERS: Final = {"constant": None, "mu": 0.0, "investment_period": None}

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

    def parts(self, position: int) -> tuple[float, float]:
        """Return what a component costs for its capacity and for its operation."""
        return float(self.capital[position]), float(self.running[position])

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
    flowed = pypsa_power_flow.is_power_flow(first)
    results = Results(framework, "optimal" if solved else "not_solved", solved)
    results.model_name = first.name
    results.objective_function_value = first.objective
    results.timestamps = _timestamps(first, options)
    results.weights = first.weighting("generators")
    results.periods = first.periods
    if first.objective_constant is not None:
        results.details["objective_constant"] = first.objective_constant
    constraints = _global_constraints(first)
    if constraints:
        results.details["global_constraints"] = constraints
    if not solved and not flowed:
        results.warnings.append(
            "the network has no objective: it has not been optimised,"
            " and the capacities are those given, not decided"
        )
    parts = [_Scenario(network, framework, _geographic(dataset)).run() for network in networks]
    given, unmet = _blend(results, parts, first.scenarios)
    results.finish()
    if solved:
        _account(results, first, given, unmet)
    elif flowed:
        pypsa_power_flow.describe(results, first, dataset.source, parts[0].reactive())
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


def _global_constraints(network: Network) -> dict[str, dict[str, Any]]:
    """Return the global constraints of the network, such as a limit on emissions, as stated."""
    table = network.component("global_constraints")
    found: dict[str, dict[str, Any]] = {}
    for position, name in enumerate(table.names):
        entry: dict[str, Any] = {}
        for attribute, default in _CONSTRAINT_TEXTS.items():
            text = table.texts(attribute, default)[position]
            if text:
                entry[attribute] = text
        for attribute, fallback in _CONSTRAINT_NUMBERS.items():
            stored = table.static.get(attribute)
            value = (
                float(stored[position])
                if stored is not None and stored.dtype.kind in "biuf"
                else math.nan
            )
            if np.isfinite(value):
                entry[attribute] = value
            elif fallback is not None:
                entry[attribute] = fallback
        found[name] = entry
    return found


def _states(component: Component, attribute: str) -> bool:
    """Tell whether any component states the attribute with a value other than zero."""
    for stored in (component.static.get(attribute), component.series.get(attribute)):
        if stored is not None and stored.dtype.kind in "biuf" and np.any(finite(stored) != 0):
            return True
    return False


def _split(bus: str) -> tuple[str, str]:
    """Return the location and the carrier that the name of a bus states, the carrier if any."""
    parts = bus.split(SEPARATOR)
    return parts[0], parts[1] if len(parts) > 1 else ""


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
        self._prices()
        self._emissions()
        return self

    # -- naming -----------------------------------------------------------------------------

    def _buses(self) -> None:
        buses = self._network.component("buses")
        carriers = buses.texts("carrier")
        for name, carrier in zip(buses.names, carriers, strict=True):
            location, named = _split(name)
            self._location[name] = location
            self._carrier[name] = named or carrier or "AC"
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
            location, named = _split(bus)
            return location, named or "AC"
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
        table: str = "",
    ) -> _Costs:
        """Return what the components cost: their capacity and their operation."""
        capital = component.numbers("capital_cost", 0.0) * capacity
        running = np.zeros(len(component))
        if dispatch is not None:
            price = component.varying("marginal_cost", 0.0, self._length)
            running = (price * dispatch * self._money[:, np.newaxis]).sum(axis=0)
        for name, series, squared, weighted in _OTHER_COSTS.get(table, ()):
            if not _states(component, name):
                continue
            price = component.varying(name, 0.0, self._length)
            amount = self._amount(component, series)
            if squared:
                amount = amount * amount
            if weighted:
                amount = amount * self._money[:, np.newaxis]
            running = running + (price * amount).sum(axis=0)
        decided = component.numbers(attribute + "_extendable", 0.0) > 0
        return _Costs(np.asarray(capital), np.asarray(running), decided)

    def _amount(self, component: Component, series: str) -> np.ndarray[Any, Any]:
        """Return the time series that a cost of operation applies to, with its default.

        PyPSA writes a series only where a value differs from its default.
        The default of `status` is on, so a committable unit that was never
        off has no series of it and stands by at every snapshot; a unit that
        is not committable has no status to pay for.
        """
        if series != "status":
            return component.flow(series, self._length)
        committable = component.numbers("committable", 0.0) > 0
        return component.varying(series, 1.0, self._length) * committable

    def _charge(
        self, location: str, technology: str, costs: _Costs, position: int, share: float = 1.0
    ) -> None:
        """Record the cost of a component; a network that has not been optimised has none."""
        if self._solved:
            fixed, variable = costs.parts(position)
            self.results.add_cost(location, technology, share * fixed, FIXED)
            self.results.add_cost(location, technology, share * variable, VARIABLE)
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
        costs = self._costs(generators, "p_nom", capacity, output, "generators")
        carriers = generators.texts("carrier")
        curtailed = self._curtailment(generators, capacity, output)
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
            if curtailed is not None and not np.isnan(curtailed[position]):
                self._add(self.results.curtailment, join(location, technology), curtailed[position])

    def _curtailment(
        self,
        generators: Component,
        capacity: np.ndarray[Any, Any],
        output: np.ndarray[Any, Any],
    ) -> np.ndarray[Any, Any] | None:
        """Return what each generator could have put out but did not, over the snapshots.

        As `n.statistics` has it: the availability `p_max_pu` times the
        capacity, less the output, for the generators whose availability
        varies with time, which is what records the resource; `NaN` for the
        others.
        """
        available = generators.series.get("p_max_pu")
        if available is None or "p" not in generators.series:
            return None
        spare = np.maximum(available * capacity - output, 0.0)
        return np.asarray((spare * self._energy[:, np.newaxis]).sum(axis=0))

    def _shortfall(self, location: str, series: np.ndarray[Any, Any]) -> None:
        unmet = np.maximum(series, 0.0)
        known = self.results.unmet_demand_timeseries
        self.results.unmet_demand_timeseries = unmet if known is None else known + unmet
        energy = float((unmet * self._energy).sum())
        if energy > 0:
            self._add(self.results.unmet_demand_by_location, location, energy)

    def _storage_units(self) -> None:
        units = self._network.component("storage_units")
        if "p_dispatch" in units.series:
            discharge = units.flow("p_dispatch", self._length)
        else:
            discharge = np.maximum(units.flow("p", self._length), 0.0)
        capacity = self._capacity(units, "p_nom")
        hours = units.numbers("max_hours", 1.0)
        costs = self._costs(units, "p_nom", capacity, discharge, "storage_units")
        levels = self._levels(units, "state_of_charge")
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
            if levels is not None:
                self.results.add_storage_level(key, levels[:, position])

    def _levels(self, component: Component, attribute: str) -> np.ndarray[Any, Any] | None:
        """Return the energy that each store holds at each snapshot, if the network was solved.

        PyPSA writes the series where it is not zero; a store that was never
        filled has none and held nothing.
        """
        if not self._solved and attribute not in component.series:
            return None
        return component.flow(attribute, self._length)

    def _stores(self) -> None:
        stores = self._network.component("stores")
        flow = stores.flow("p", self._length)
        withdrawal = np.maximum(flow, 0.0)
        capacity = self._capacity(stores, "e_nom")
        costs = self._costs(stores, "e_nom", capacity, flow, "stores")
        levels = self._levels(stores, "e")
        for position, (name, bus) in enumerate(zip(stores.names, stores.texts("bus"), strict=True)):
            location, carrier = self._place(bus)
            technology = self._technology(name, location)
            key = join(location, technology)
            self._add(self.results.storage_capacities, key, capacity[position])
            self._deliver(technology, location, carrier, withdrawal[:, position])
            self.results.add_dispatch(technology, withdrawal[:, position])
            self._charge(location, technology, costs, position)
            self._register(technology, _STORAGE, carrier)
            if levels is not None:
                self.results.add_storage_level(key, levels[:, position])

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
        costs = self._costs(links, "p_nom", capacity, flows.get(0), "links")
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

    def _prices(self) -> None:
        """Record the marginal price of each bus, if the network was solved for them.

        PyPSA writes the series where a price is not zero; a bus whose price
        stays zero has none. A bus named `north::electricity` is the price of
        `electricity` at `north`; a bus named with more parts keeps its name,
        which tells it from the bus of the location and the carrier; any
        other bus is named by its location and its carrier.
        """
        buses = self._network.component("buses")
        if "marginal_price" not in buses.series:
            return
        prices = buses.flow("marginal_price", self._length)
        for position, name in enumerate(buses.names):
            key = name if SEPARATOR in name else join(*self._place(name))
            self.results.prices[key] = prices[:, position]

    def _emissions(self) -> None:
        """Record what each component emits, as PyPSA counts it towards a limit of emissions.

        A generator emits what it burns, its output over its efficiency,
        times what its carrier emits per unit; every generator is listed
        once any carrier emits, with nothing for a carrier that does not. A
        storage unit or a store whose carrier emits and that is not cyclic
        emits what it gives off over the snapshots, the energy it held at
        the start less what it holds at the end.
        """
        carriers = self._network.component("carriers")
        intensity = dict(
            zip(carriers.names, carriers.numbers(_INTENSITY, 0.0).tolist(), strict=True)
        )
        generators = self._network.component("generators")
        if not any(intensity.values()) or "p" not in generators.series:
            return
        output = generators.flow("p", self._length)
        burnt = output / generators.varying("efficiency", 1.0, self._length)
        emitted = (burnt * self._energy[:, np.newaxis]).sum(axis=0)
        kinds = generators.texts("carrier")
        for position, (name, bus) in enumerate(
            zip(generators.names, generators.texts("bus"), strict=True)
        ):
            location, _ = self._place(bus)
            technology = self._technology(name, location)
            if {kinds[position].lower(), technology.lower()} & _SHORTFALL:
                continue
            rate = intensity.get(kinds[position], 0.0)
            self.results.add_emissions(location, technology, rate * emitted[position])
        for table, level, initial, cyclic in (
            (
                "storage_units",
                "state_of_charge",
                "state_of_charge_initial",
                "cyclic_state_of_charge",
            ),
            ("stores", "e", "e_initial", "e_cyclic"),
        ):
            component = self._network.component(table)
            if level not in component.series:
                continue
            held = component.flow(level, self._length)
            start = component.numbers(initial, 0.0)
            circular = component.numbers(cyclic, 0.0) > 0
            for position, (name, bus) in enumerate(
                zip(component.names, component.texts("bus"), strict=True)
            ):
                rate = intensity.get(component.texts("carrier")[position], 0.0)
                if rate and not circular[position]:
                    location, _ = self._place(bus)
                    technology = self._technology(name, location)
                    released = start[position] - held[-1, position]
                    self.results.add_emissions(location, technology, rate * released)

    def reactive(self) -> dict[str, np.ndarray[Any, Any]]:
        """Return the reactive power that each technology supplies at each location.

        The generators and the storage units supply it. A network holds it
        only if it was solved for it, with a non-linear power flow; it then
        has a series of reactive power somewhere, and a unit that has none
        supplied nothing.
        """
        found: dict[str, np.ndarray[Any, Any]] = {}
        if not any(
            name in component.series
            for component in self._network.components.values()
            for name in ("q", "q0", "q1")
        ):
            return found
        for table in ("generators", "storage_units"):
            component = self._network.component(table)
            supplied = component.flow("q", self._length)
            for position, (name, bus) in enumerate(
                zip(component.names, component.texts("bus"), strict=True)
            ):
                location, _ = self._place(bus)
                key = join(location, self._technology(name, location))
                known = found.get(key)
                series = supplied[:, position]
                found[key] = series if known is None else known + series
        return found

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
            "curtailment",
            "demand_by_location",
            "unmet_demand_by_location",
            "emissions_by_location",
        ):
            target = getattr(results, name)
            for key, value in getattr(found, name).items():
                target[key] = target.get(key, 0.0) + share * value
        for kind, costs_by_location in (
            (FIXED, found.fixed_costs_by_location),
            (VARIABLE, found.variable_costs_by_location),
        ):
            for location, costs in costs_by_location.items():
                for technology, cost in costs.items():
                    results.add_cost(location, technology, share * cost, kind)
        for technology, series in found.dispatch.items():
            results.add_dispatch(technology, share * series)
        for key, series in found.storage_levels.items():
            results.add_storage_level(key, share * series)
        for key, series in found.prices.items():
            known = results.prices.get(key)
            results.prices[key] = share * series if known is None else known + share * series
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
