"""Results of AdOpT-NET0.

AdOpT-NET0 writes an HDF5 file of nested groups whose names are the names of
the model:

```text
summary/                                        one value for each figure of the run
topology/                                       nodes, periods and carriers
design/nodes/<period>/<node>/<technology>/      size and cost of a technology
design/networks/<period>/<network>/<arc>/       size and cost of an arc of a network
operation/technology_operation/<period>/<node>/<technology>/
operation/energy_balance/<period>/<node>/<carrier>/
operation/networks/<period>/<network>/<arc>/
```

The file has neither dimensions nor attributes, and it records no times. Six
of its properties shape the document:

* **Imports and exports are no technologies** in AdOpT-NET0 but part of the
  energy balance of a node. The document reports them like technologies, named
  `import_<carrier>` and `export_<carrier>`, because without them the
  supply of a model that buys its energy would be empty. A flow that stays
  below one millionth at every time is what a solver leaves behind, not an
  import, and is not reported.
* **The size of a technology is in its own unit.** For a technology that
  consists of units of a rated power, such as a wind turbine, it is the number
  of units, and the capacity is the size times the rated power. For a store it
  is the energy the store holds.
* **An arc has a direction.** The group of an arc is named by the two nodes
  written one after the other, which is ambiguous; the nodes are read from the
  datasets `fromNode` and `toNode` instead. A connection that works in both
  directions appears as two arcs of the same size and cost, which AdOpT-NET0
  charges once; in the document each of the two arcs bears half of it.
* **A file holds one or several investment periods.** The document reports
  one of them, the first unless the caller names another. Its `objective` is
  then the cost of that period, while the figures of the summary, which are
  reported under `details`, are those of all periods together.
  AdOpT-NET0 0.1.10 writes the design of the nodes, the operation and the
  energy balances of the last period in place of those of every period; a file
  whose periods hold the same results gives rise to a warning.
* **Typical days may stand for the year.** If the model aggregates time and
  solves the typical days alone, the time series of the file cover the typical
  days. The document gives the series of the whole modelled time, in which
  each time has the values of the typical day that stands for it, so that its
  totals are those of the model. The variable cost of a technology, of which
  the file has the sum over the typical days, is scaled with the flow of the
  technology to that end.
* **The total cost is that of the summary.** It may hold costs that belong to
  no technology: those of emissions and of violated balances. The document
  names them in a warning.

How each key of the document follows from the file is described in the
documentation under *Frameworks*.
"""

from __future__ import annotations

import math
from typing import Any, Final

import numpy as np

from coati.errors import ExtractionError
from coati.frameworks import Framework
from coati.labeled import finite, numbers_of, texts_of
from coati.model import Dataset, Group, Variable
from coati.results.document import INACTIVE, Results, join, net_flows, succeeded
from coati.results.options import ExtractOptions, synthesize_timestamps

__all__ = ["extract"]

_SUPPLY: Final = "supply"
_DEMAND: Final = "demand"
_STORAGE: Final = "storage"
_CONVERSION: Final = "conversion"
_TRANSMISSION: Final = "transmission"

_INPUT: Final = "_input"
_OUTPUT: Final = "_output"

# Figures of the summary that are no result: the folder of the run on the machine that ran it.
_PRIVATE: Final = frozenset({"time_stamp"})

# What AdOpT-NET0 writes in place of a value that is not set.
_UNSET: Final = -1

# Costs of the summary that belong to no technology, with the sign they have in the total.
_OTHER_COSTS: Final = (("violation_cost", 1.0), ("carbon_cost", 1.0), ("carbon_revenue", -1.0))

# The groups that hold the results of each investment period besides the design of the networks.
_BY_PERIOD: Final = (
    ("design", "nodes"),
    ("operation", "technology_operation"),
    ("operation", "energy_balance"),
)

# How far the total cost may be from the costs that make it up, relative and absolute.
_CLOSE: Final = (1e-6, 1e-3)


def extract(dataset: Dataset, framework: Framework, options: ExtractOptions) -> Results:
    """Make the results of a file of AdOpT-NET0.

    Raises:
        ExtractionError: The file lacks the investment period that was asked for.
    """
    return _Extractor(dataset, framework, options).run()


def _child(group: Group | None, name: str) -> Group | None:
    """Return the group `name` within `group`, whatever the case of its name."""
    if group is None:
        return None
    found = group.groups.get(name)
    if found is not None:
        return found
    for candidate, child in group.groups.items():
        if candidate.lower() == name.lower():
            return child
    return None


def _descend(group: Group | None, *names: str) -> Group | None:
    for name in names:
        group = _child(group, name)
    return group


def _scalar(variable: Variable | None) -> Any:
    """Return the one value of a dataset: a number, a text or `None`."""
    if variable is None or variable.size != 1:
        return None
    if variable.type_name == "string":
        return texts_of(variable)[0]
    if variable.dtype.kind not in "biuf":
        return None
    value = float(numbers_of(variable).reshape(-1)[0])
    return None if np.isnan(value) else value


def _number(group: Group, name: str, default: float = 0.0) -> float:
    value = _scalar(group.variables.get(name))
    return float(value) if isinstance(value, float) else default


def _length_of_series(group: Group | None) -> int | None:
    """Return the length of the first time series in or below `group`."""
    for child in group.walk() if group is not None else ():
        for variable in child.variables.values():
            if variable.ndim == 1 and variable.dtype.kind in "biuf":
                return variable.shape[0]
    return None


def _alike(one: Group, other: Group) -> bool:
    """Tell whether two groups hold the same groups and the same values."""
    if list(one.groups) != list(other.groups) or list(one.variables) != list(other.variables):
        return False
    for name, variable in one.variables.items():
        twin = other.variables[name]
        if variable.shape != twin.shape or variable.dtype != twin.dtype:
            return False
        if variable.dtype.kind in "biuf":
            if not np.array_equal(variable.read(), twin.read(), equal_nan=True):
                return False
        elif texts_of(variable) != texts_of(twin):
            return False
    return all(_alike(child, other.groups[name]) for name, child in one.groups.items())


class _Extractor:
    def __init__(self, dataset: Dataset, framework: Framework, options: ExtractOptions) -> None:
        self._dataset = dataset
        self._options = options
        self._summary = self._read_summary()
        self._carriers = self._read_topology("carriers")
        self._period = ""
        self._periods: list[str] = []
        self._length = 0
        self._typical = 0
        self._positions: np.ndarray[Any, Any] | None = None
        self._arrivals: dict[tuple[str, str], np.ndarray[Any, Any]] = {}
        self._demand: np.ndarray[Any, Any] | None = None
        self._results = Results(framework, "", False)

    def run(self) -> Results:
        results = self._results
        self._describe_run()
        self._period = self._choose_period()
        self._typical_days()
        self._technologies()
        self._energy_balance()
        self._networks()
        results.demand_timeseries = self._demand
        results.transmission_flow = net_flows(self._arrivals)
        results.timestamps = synthesize_timestamps(self._options, self._length)
        results.finish()
        self._account()
        return results

    # -- reading ----------------------------------------------------------------------------

    def _read_summary(self) -> dict[str, Any]:
        summary = _child(self._dataset, "summary")
        if summary is None:
            return {}
        figures = {name: _scalar(variable) for name, variable in summary.variables.items()}
        return {
            name: value
            for name, value in figures.items()
            if value is not None and name not in _PRIVATE
        }

    def _read_topology(self, name: str) -> list[str]:
        topology = _child(self._dataset, "topology")
        variable = topology.variables.get(name) if topology is not None else None
        if variable is None:
            return []
        return [text for text in texts_of(variable) if text is not None]

    def _series(self, group: Group | None, name: str) -> np.ndarray[Any, Any] | None:
        """Read a time series as the file has it: of the typical days, if these stand for all."""
        variable = group.variables.get(name) if group is not None else None
        if variable is None or variable.dtype.kind not in "biuf" or variable.ndim != 1:
            return None
        return finite(numbers_of(variable))

    def _over_time(self, series: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
        """Return a time series over the whole modelled time, and note its length."""
        if self._positions is not None and series.shape[0] == self._typical:
            series = series[self._positions]
        self._length = max(self._length, int(series.shape[0]))
        return series

    def _weight(self, *flows: np.ndarray[Any, Any] | None) -> float:
        """Return what a sum over the typical days is to be multiplied with.

        The sum of a quantity over the whole modelled time is wanted, the file
        has its sum over the typical days. The two are in the ratio of the
        sums of the flows that the quantity is proportional to.
        """
        if self._positions is None:
            return 1.0
        typical = [flow for flow in flows if flow is not None and flow.shape[0] == self._typical]
        plain = math.fsum(float(np.abs(flow).sum()) for flow in typical)
        if plain <= 0:
            return len(self._positions) / self._typical
        whole = math.fsum(float(np.abs(flow[self._positions]).sum()) for flow in typical)
        return whole / plain

    def _carrier_of(self, name: str, suffix: str) -> str | None:
        """Return the carrier of a dataset such as `electricity_output`."""
        if not name.endswith(suffix):
            return None
        carrier = name[: -len(suffix)]
        if not carrier or (self._carriers and carrier not in self._carriers):
            return None
        return carrier

    # -- the parts of the document ----------------------------------------------------------

    def _describe_run(self) -> None:
        results = self._results
        summary = self._summary
        condition = summary.get("solver_status")
        solved = _descend(self._dataset, "design", "nodes") is not None
        if not isinstance(condition, str) or not condition:
            condition = "unknown" if solved else "not_solved"
        results.termination_condition = condition
        results.success = solved and succeeded(condition)
        case = summary.get("case")
        results.model_name = case if isinstance(case, str) and case != str(_UNSET) else None
        if summary:
            results.details["summary"] = {
                name: value for name, value in summary.items() if value != _UNSET
            }

    def _choose_period(self) -> str:
        periods = self._read_topology("periods")
        design = _descend(self._dataset, "design", "nodes")
        if not periods and design is not None:
            periods = list(design.groups)
        wanted = self._options.period
        if wanted is not None and wanted not in periods:
            known = ", ".join(periods) or "none"
            raise ExtractionError(
                f"{self._dataset.source}: no investment period {wanted!r}; the file has {known}"
            )
        if not periods:
            return ""
        chosen = wanted or periods[0]
        self._periods = periods
        if len(periods) > 1:
            self._results.details["periods"] = periods
            self._results.details["period"] = chosen
            self._results.warnings.append(
                f"the file holds {len(periods)} investment periods; the document reports"
                f" {chosen!r}, and its objective is the cost of that period"
            )
            if self._periods_are_alike():
                self._results.warnings.append(
                    f"the file holds the same results for each of its {len(periods)} investment"
                    " periods, except for the design of the networks; AdOpT-NET0 0.1.10 is"
                    f" known to write the results of the last period, {periods[-1]!r}, in place"
                    " of those of every period"
                )
        return chosen

    def _periods_are_alike(self) -> bool:
        """Tell whether the file holds the same results for every investment period."""
        for names in _BY_PERIOD:
            groups = [_descend(self._dataset, *names, period) for period in self._periods]
            first = groups[0]
            if first is None or not (first.groups or first.variables):
                return False
            if not all(other is not None and _alike(first, other) for other in groups[1:]):
                return False
        return True

    def _technologies(self) -> None:
        design = _descend(self._dataset, "design", "nodes", self._period)
        operation = _descend(self._dataset, "operation", "technology_operation", self._period)
        for node, at_node in (design.groups if design is not None else {}).items():
            running = _child(operation, node)
            for technology, sized in at_node.groups.items():
                self._technology(node, technology, sized, _child(running, technology))

    def _technology(self, node: str, name: str, sized: Group, running: Group | None) -> None:
        results = self._results
        inputs, outputs = self._flows(running)
        weight = self._weight(*(inputs or outputs).values())
        stores = running is not None and "storage_level" in running.variables
        kind = _kind(stores, bool(inputs), bool(outputs))
        key = join(node, name)
        size = _number(sized, "size")
        if stores:
            results.storage_capacities[key] = size
            results.capacities[key] = _number(sized, "capacity_discharge", size)
        else:
            results.capacities[key] = size * _number(sized, "rated_power", 1.0)
        cost = _number(sized, "capex_tot") + _number(sized, "opex_fixed_tot")
        results.add_cost(node, name, cost + weight * _number(sized, "opex_variable"))
        for carrier, flow in outputs.items():
            series = self._over_time(flow)
            results.generation[join(node, name, carrier)] = float(series.sum())
            if kind != _DEMAND:
                results.add_dispatch(name, series)
        for flow in inputs.values():
            self._over_time(flow)
        results.tech_metadata.setdefault(
            name, {"parent": kind, "carrier_out": next(iter(outputs), "")}
        )

    def _flows(
        self, running: Group | None
    ) -> tuple[dict[str, np.ndarray[Any, Any]], dict[str, np.ndarray[Any, Any]]]:
        """Return what a technology takes in and puts out, by carrier, as the file has it."""
        inputs: dict[str, np.ndarray[Any, Any]] = {}
        outputs: dict[str, np.ndarray[Any, Any]] = {}
        for name in running.variables if running is not None else ():
            for suffix, target in ((_INPUT, inputs), (_OUTPUT, outputs)):
                carrier = self._carrier_of(name, suffix)
                series = self._series(running, name) if carrier else None
                if carrier is not None and series is not None:
                    target[carrier] = np.maximum(series, 0.0)
        return inputs, outputs

    def _energy_balance(self) -> None:
        balance = _descend(self._dataset, "operation", "energy_balance", self._period)
        for node, at_node in (balance.groups if balance is not None else {}).items():
            for carrier, flows in at_node.groups.items():
                self._balance(node, carrier, flows)

    def _balance(self, node: str, carrier: str, flows: Group) -> None:
        results = self._results
        demand = self._series(flows, "demand")
        if demand is not None:
            consumed = self._over_time(np.abs(demand))
            self._demand = consumed if self._demand is None else self._demand + consumed
            if float(consumed.sum()) > 0:
                known = results.demand_by_location.get(node, 0.0)
                results.demand_by_location[node] = known + float(consumed.sum())
        for name, kind, sign in (
            ("import", _SUPPLY, 1.0),
            ("generic_production", _SUPPLY, 0.0),
            ("export", _DEMAND, -1.0),
        ):
            series = self._series(flows, name)
            if series is None or float(np.abs(series).max(initial=0.0)) < INACTIVE:
                continue
            series = self._over_time(np.maximum(series, 0.0))
            technology = f"{name}_{carrier}"
            price = self._series(flows, f"{name}_price")
            price = self._over_time(price) if price is not None else None
            if price is not None and price.shape == series.shape:
                results.add_cost(node, technology, sign * float((series * price).sum()))
            results.tech_metadata.setdefault(
                technology, {"parent": kind, "carrier_out": carrier if kind == _SUPPLY else ""}
            )
            if kind == _SUPPLY:
                results.generation[join(node, technology, carrier)] = float(series.sum())
                results.add_dispatch(technology, series)
            else:
                exported = results.details.setdefault("exported", {})
                exported[join(node, carrier)] = float(series.sum())

    def _networks(self) -> None:
        design = _descend(self._dataset, "design", "networks", self._period)
        operation = _descend(self._dataset, "operation", "networks", self._period)
        for network, arcs in (design.groups if design is not None else {}).items():
            carrier = self._carrier_of_network(network)
            self._results.tech_metadata.setdefault(
                network, {"parent": _TRANSMISSION, "carrier_out": carrier}
            )
            running = _child(operation, network)
            fixed = {
                _ends(sized): _fixed_cost(sized) for sized in arcs.groups.values() if _ends(sized)
            }
            for arc, sized in arcs.groups.items():
                self._arc(network, carrier, arc, sized, _child(running, arc), fixed)

    def _arc(
        self,
        network: str,
        carrier: str,
        arc: str,
        sized: Group,
        running: Group | None,
        fixed: dict[tuple[str, str] | None, tuple[float, float]],
    ) -> None:
        results = self._results
        ends = _ends(sized)
        if ends is None:
            results.warnings.append(
                f"the arc {arc!r} of the network {network!r} does not name its nodes;"
                " it is not reported"
            )
            return
        origin, destination = ends
        size, cost = fixed[ends]
        technology = f"{network}:{destination}"
        results.capacities[join(origin, technology)] = size
        results.tech_metadata.setdefault(
            technology, {"parent": _TRANSMISSION, "carrier_out": carrier}
        )
        twin = fixed.get((destination, origin))
        if twin is not None and np.allclose(twin, (size, cost)):
            cost /= 2  # the two directions of one connection share what it costs
        flow = self._series(running, "flow")
        running_cost = self._weight(flow) * _number(sized, "opex_variable")
        results.add_cost(origin, technology, cost + running_cost)
        if flow is None:
            return
        losses = self._series(running, "losses")
        arriving = self._over_time(
            flow if losses is None or losses.shape != flow.shape else flow - losses
        )
        arriving = np.maximum(arriving, 0.0)
        known = self._arrivals.get((origin, destination))
        self._arrivals[origin, destination] = arriving if known is None else known + arriving
        if carrier:
            key = join(destination, f"{network}:{origin}", carrier)
            results.generation[key] = float(arriving.sum())

    def _carrier_of_network(self, network: str) -> str:
        """Return the carrier of a network: the only one, or the one its name starts with."""
        if len(self._carriers) == 1:
            return self._carriers[0]
        matching = [
            carrier for carrier in self._carriers if network.lower().startswith(carrier.lower())
        ]
        return max(matching, key=len) if matching else ""

    def _typical_days(self) -> None:
        """Find out whether typical days stand for the modelled time, and which for which."""
        clustering = _descend(self._dataset, "k_means_specs", self._period)
        if clustering is None or not clustering.variables:
            return
        self._results.details["typical_days"] = True
        factors = self._series(clustering, "factors")
        sequence = self._series(clustering, "sequence")
        if factors is None or sequence is None or not 0 < len(factors) < len(sequence):
            return
        positions = sequence.astype(np.int64) - 1
        if positions.min() < 0 or positions.max() >= len(factors):
            return
        balance = _descend(self._dataset, "operation", "energy_balance", self._period)
        if _length_of_series(balance) != len(factors):
            return  # the file has the series of the whole modelled time
        self._typical = len(factors)
        self._positions = positions

    def _account(self) -> None:
        """Set the cost of the system and compare it with the costs of the technologies."""
        results = self._results
        summary = self._summary
        listed = math.fsum(
            cost for costs in results.costs_by_location.values() for cost in costs.values()
        )
        stated = next(
            (
                summary[name]
                for name in ("total_npv", "total_cost")
                if isinstance(summary.get(name), float)
            ),
            None,
        )
        if stated is not None and summary.get("objective") == "costs":
            results.objective_function_value = stated
        if not results.costs_by_location and stated is None:
            return
        if stated is None or len(self._periods) > 1:
            results.objective = listed
            return
        results.objective = stated
        others = {
            name: sign * summary[name]
            for name, sign in _OTHER_COSTS
            if isinstance(summary.get(name), float) and summary[name] != 0
        }
        relative, absolute = _CLOSE
        counted = listed + math.fsum(others.values())
        if not math.isclose(counted, stated, rel_tol=relative, abs_tol=absolute):
            results.warnings.append(
                f"the total cost is {stated:.10g}, the costs that the file attributes to"
                f" technologies, networks and carriers add up to {counted:.10g}"
            )
        elif others:
            named = ", ".join(f"{name} {abs(cost):.10g}" for name, cost in others.items())
            results.warnings.append(
                f"the total cost of {stated:.10g} includes costs that belong to no technology"
                f" and are not listed: {named}"
            )


def _ends(sized: Group) -> tuple[str, str] | None:
    """Return the node an arc starts at and the node it leads to."""
    origin = _scalar(sized.variables.get("fromNode"))
    destination = _scalar(sized.variables.get("toNode"))
    if isinstance(origin, str) and isinstance(destination, str):
        return origin, destination
    return None


def _fixed_cost(sized: Group) -> tuple[float, float]:
    """Return the size of an arc and what it costs whether or not it carries anything."""
    return _number(sized, "size"), _number(sized, "capex") + _number(sized, "opex_fixed")


def _kind(stores: bool, takes: bool, gives: bool) -> str:
    """Return the kind of a technology from what it does."""
    if stores:
        return _STORAGE
    if takes and gives:
        return _CONVERSION
    if takes:
        return _DEMAND
    return _SUPPLY
