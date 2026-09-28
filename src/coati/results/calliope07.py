"""Results of Calliope 0.7.

Calliope 0.7 writes three groups. `inputs` holds the parameters of the model,
`results` the solution, and the attributes of `attrs` the configuration and
the record of the run as YAML. The arrays have the dimensions `nodes`,
`techs`, `carriers`, `costs` and `timesteps`; an element that does not
exist, such as a technology at a node where it is not installed, is `NaN`.

Two modes add to this layout:

* In **SPORES** mode the results have a further dimension `spores`. The
  document reports the first of them, the solution of least cost, and lists
  the cost, the capacities and the generation of each under `details.spores`.
* In **operate** mode the capacities are parameters, found in `inputs`, and
  the costs have one entry for each window of the horizon.

How each key of the document follows from the file is described in the
documentation under *Frameworks*.
"""

from __future__ import annotations

from typing import Any, Final

import numpy as np

from coati import yamltext
from coati.errors import ExtractionError
from coati.frameworks import Framework
from coati.labeled import LabeledArray, labels_of, texts_of, weights_of
from coati.model import Dataset, Group
from coati.results.document import Results, join, net_flows, solutions_of_spores, succeeded
from coati.results.options import ExtractOptions

__all__ = ["extract"]

_NODES: Final = "nodes"
_TECHS: Final = "techs"
_CARRIERS: Final = "carriers"
_COSTS: Final = "costs"
_TIME: Final = "timesteps"
_SPORES: Final = "spores"

_DEMAND: Final = "demand"
_TRANSMISSION: Final = "transmission"


def extract(dataset: Dataset, framework: Framework, options: ExtractOptions) -> Results:
    """Make the results of a file of Calliope 0.7.

    Raises:
        ExtractionError: The file lacks the group `results` or a variable
            has other dimensions than Calliope gives it.
    """
    return _Extractor(dataset, framework, options).run()


class _Extractor:
    def __init__(self, dataset: Dataset, framework: Framework, options: ExtractOptions) -> None:
        self._dataset = dataset
        self._options = options
        self._inputs = dataset.groups.get("inputs") or Group("inputs", "/inputs")
        self._solution = dataset.groups.get("results") or Group("results", "/results")
        records = dataset.groups.get("attrs")
        self._runtime = records.attributes.get("runtime") if records else None
        self._config = records.attributes.get("config") if records else None
        self._spores: tuple[str, ...] = ()
        self._base: dict[str, str] = {}
        self._results = Results(framework, "", False)

    def run(self) -> Results:
        results = self._results
        self._describe_run()
        self._base = self._texts(_TECHS, "base_tech")
        self._timestamps()
        flow_out = self._array("flow_out", _NODES, _TECHS, _CARRIERS, _TIME)
        flow_in = self._array("flow_in", _NODES, _TECHS, _CARRIERS, _TIME)
        capacity = self._capacity()
        self._capacities(capacity)
        self._generation(flow_out)
        self._transmission(flow_out, capacity)
        self._demand(flow_in)
        self._unmet_demand()
        self._costs()
        self._technologies(flow_out)
        self._coordinates()
        self._list_spores()
        results.finish()
        return results

    # -- reading ----------------------------------------------------------------------------

    def _array(self, name: str, *dims: str, group: Group | None = None) -> LabeledArray | None:
        """Read a variable of the solution, reduced to the first of the SPORES."""
        group = group or self._solution
        variable = group.variables.get(name)
        if variable is None:
            return None
        array = LabeledArray.read(variable, group)
        if _SPORES in array:
            self._spores = array.labels[_SPORES]
            array = array.select(_SPORES, self._spores[0])
        unexpected = [dim for dim in array.dims if dim not in dims]
        if unexpected:
            raise ExtractionError(
                f"{variable.path} has the dimensions {', '.join(array.dims)};"
                f" expected are {', '.join(dims)}"
            )
        return array

    def _texts(self, dim: str, name: str) -> dict[str, str]:
        """Read a text for each label of `dim` from the inputs, where there is one."""
        variable = self._inputs.variables.get(name)
        if variable is None or variable.dimensions != (dim,):
            return {}
        labels = labels_of(self._inputs, dim, variable.shape[0])
        return {
            label: text
            for label, text in zip(labels, texts_of(variable), strict=True)
            if text is not None
        }

    def _weights(self, length: int) -> np.ndarray[Any, Any]:
        """Return the weight of each time: how often the model counts it."""
        return weights_of(self._inputs.variables.get("timestep_weights"), length)

    # -- the parts of the document ----------------------------------------------------------

    def _describe_run(self) -> None:
        results = self._results
        solved = any(name not in self._solution.dimensions for name in self._solution.variables)
        condition = yamltext.scalar(self._runtime, "termination_condition")
        if condition is None:
            condition = "unknown" if solved else "not_solved"
        results.termination_condition = condition
        results.success = solved and succeeded(condition)
        results.model_name = yamltext.scalar(self._config, "init", "name")
        results.solver = yamltext.scalar(self._config, "solve", "solver")
        mode = yamltext.scalar(self._config, "init", "mode")
        if mode is not None:
            results.details["mode"] = mode
        if not solved:
            results.warnings.append("the file holds no results: the model has not been solved")
        objective = yamltext.scalar(self._config, "build", "objective") or "min_cost_optimisation"
        value = self._array(objective, _TIME)
        if value is not None and np.isfinite(value.values).any():
            results.objective_function_value = float(np.nansum(value.values))

    def _timestamps(self) -> None:
        for group in (self._solution, self._inputs):
            coordinate = group.variables.get(_TIME)
            if coordinate is not None:
                self._results.timestamps = texts_of(coordinate)
                self._results.weights = self._weights(coordinate.shape[0])
                return

    def _capacity(self) -> LabeledArray | None:
        """Return the capacity of each technology at each node."""
        return self._decided_or_given("flow_cap")

    def _decided_or_given(self, name: str) -> LabeledArray | None:
        """Read a capacity from the solution or, in operate mode, from the inputs."""
        decided = self._array(name, _NODES, _TECHS, _CARRIERS)
        if decided is not None:
            return decided.max(_CARRIERS)
        given = self._array(name, _NODES, _TECHS, _CARRIERS, group=self._inputs)
        if given is None:
            return None
        return self._at_nodes(given.max(_CARRIERS))

    def _at_nodes(self, array: LabeledArray) -> LabeledArray | None:
        """Spread a parameter over the nodes at which each technology is defined.

        Calliope stores a parameter that is the same everywhere without the
        dimension of the nodes. The solution has one value for each node and
        technology, and so has the document.
        """
        if _NODES in array and _TECHS in array:
            return array
        defined = self._array("definition_matrix", _NODES, _TECHS, _CARRIERS, group=self._inputs)
        if defined is None or _NODES not in defined or _TECHS not in defined:
            return None
        defined = defined.max(_CARRIERS)
        nodes, technologies = defined.labels[_NODES], defined.labels[_TECHS]
        values = np.full((len(nodes), len(technologies)), np.nan)
        for labels, value in array.items():
            given = dict(zip(array.dims, labels, strict=True))
            for row, node in enumerate(nodes):
                for column, technology in enumerate(technologies):
                    if (
                        given.get(_NODES, node) != node
                        or given.get(_TECHS, technology) != technology
                    ):
                        continue
                    if defined.select(_NODES, node).select(_TECHS, technology).values > 0:
                        values[row, column] = value
        return LabeledArray(values, (_NODES, _TECHS), {_NODES: nodes, _TECHS: technologies})

    def _capacities(self, capacity: LabeledArray | None) -> None:
        if capacity is not None:
            for labels, value in _by(capacity, _NODES, _TECHS):
                self._results.capacities[join(*labels)] = value
        storage = self._decided_or_given("storage_cap")
        if storage is not None:
            for labels, value in _by(storage, _NODES, _TECHS):
                self._results.storage_capacities[join(*labels)] = value

    def _generation(self, flow_out: LabeledArray | None) -> None:
        if flow_out is None:
            return
        weights = self._weights(len(flow_out.labels[_TIME]))
        totals = flow_out.scale(_TIME, weights).sum(_TIME)
        for labels, value in _by(totals, _NODES, _TECHS, _CARRIERS):
            self._results.generation[join(*labels)] = value
        for technology in flow_out.labels[_TECHS]:
            if self._base.get(technology) in (_DEMAND, _TRANSMISSION):
                continue
            self._results.add_dispatch(
                technology, flow_out.select(_TECHS, technology).series(_TIME)
            )

    def _transmission(self, flow_out: LabeledArray | None, capacity: LabeledArray | None) -> None:
        if flow_out is None:
            return
        origins = self._texts(_TECHS, "link_from")
        destinations = self._texts(_TECHS, "link_to")
        arrivals: dict[tuple[str, str], np.ndarray[Any, Any]] = {}
        for technology in flow_out.labels[_TECHS]:
            if self._base.get(technology) != _TRANSMISSION:
                continue
            ends = _ends(technology, origins, destinations, capacity, flow_out)
            if ends is None:
                self._results.warnings.append(
                    f"the transmission technology {technology!r} does not connect two nodes;"
                    " its flow is not reported"
                )
                continue
            flow = flow_out.select(_TECHS, technology)
            for origin, destination in (ends, ends[::-1]):
                arriving = flow.select(_NODES, destination).series(_TIME)
                known = arrivals.get((origin, destination))
                arrivals[origin, destination] = arriving if known is None else known + arriving
        self._results.transmission_flow = net_flows(arrivals)

    def _demand(self, flow_in: LabeledArray | None) -> None:
        if flow_in is None:
            return
        demands = [name for name in flow_in.labels[_TECHS] if self._base.get(name) == _DEMAND]
        if not demands:
            return
        consumed = flow_in.take(_TECHS, demands).absolute()
        self._results.demand_timeseries = consumed.series(_TIME)
        weights = self._weights(len(flow_in.labels[_TIME]))
        totals = consumed.scale(_TIME, weights).sum(_TIME, _TECHS, _CARRIERS)
        for (node,), value in _by(totals, _NODES):
            if value > 0:
                self._results.demand_by_location[node] = value

    def _unmet_demand(self) -> None:
        unmet = self._array("unmet_demand", _NODES, _CARRIERS, _TIME)
        if unmet is None or _TIME not in unmet:
            return
        self._results.unmet_demand_timeseries = unmet.series(_TIME)
        weights = self._weights(len(unmet.labels[_TIME]))
        for (node,), value in _by(unmet.scale(_TIME, weights).sum(_TIME, _CARRIERS), _NODES):
            if value > 0:
                self._results.unmet_demand_by_location[node] = value

    def _costs(self) -> None:
        cost = self._array("cost", _NODES, _TECHS, _COSTS, _TIME)
        if cost is None:
            return
        if _COSTS in cost:
            cost = cost.scale(_COSTS, self._cost_weights(cost.labels[_COSTS]))
        total = cost.sum(_COSTS, _TIME)
        for (node, technology), value in _by(total, _NODES, _TECHS):
            self._results.add_cost(node, technology, value)
        if np.isfinite(total.values).any():
            self._results.objective = float(np.nansum(total.values))

    def _cost_weights(self, classes: tuple[str, ...]) -> np.ndarray[Any, Any]:
        """Return the weight of each class of cost in the objective; one unless given."""
        weights = np.ones(len(classes))
        given = self._array("objective_cost_weights", _COSTS, group=self._inputs)
        if given is None or _COSTS not in given:
            return weights
        known = dict(zip(given.labels[_COSTS], given.values.tolist(), strict=True))
        for position, name in enumerate(classes):
            weight = known.get(name, 1.0)
            weights[position] = 1.0 if np.isnan(weight) else weight
        return weights

    def _technologies(self, flow_out: LabeledArray | None) -> None:
        names = self._texts(_TECHS, "name") if self._options.labels else {}
        colors = self._texts(_TECHS, "color") if self._options.labels else {}
        carriers = self._output_carriers(flow_out)
        for technology, base in self._base.items():
            entry = {"parent": base, "carrier_out": carriers.get(technology, "")}
            if technology in names:
                entry["display_name"] = names[technology]
            if technology in colors:
                entry["color"] = colors[technology]
            self._results.tech_metadata[technology] = entry

    def _output_carriers(self, flow_out: LabeledArray | None) -> dict[str, str]:
        """Return the first carrier that each technology puts out."""
        produced = self._array("carrier_out", _NODES, _TECHS, _CARRIERS, group=self._inputs)
        if produced is None or _CARRIERS not in produced or _TECHS not in produced:
            produced = flow_out.absolute().sum(_TIME) if flow_out is not None else None
        if produced is None or _CARRIERS not in produced or _TECHS not in produced:
            return {}
        carriers: dict[str, str] = {}
        by_technology = produced.sum(_NODES)
        for labels, value in _by(by_technology, _TECHS, _CARRIERS):
            if value > 0:
                carriers.setdefault(labels[0], labels[1])
        return carriers

    def _coordinates(self) -> None:
        latitude = self._array("latitude", _NODES, group=self._inputs)
        longitude = self._array("longitude", _NODES, group=self._inputs)
        if latitude is None or longitude is None or _NODES not in latitude:
            return
        east = dict(_by(longitude, _NODES))
        for labels, north in _by(latitude, _NODES):
            if labels in east:
                self._results.coordinates[labels[0]] = [north, east[labels]]

    def _list_spores(self) -> None:
        """List what differs between the SPORES: cost, capacities and generation.

        Each is made as the document makes it for the first of them: the cost
        counts the classes of cost as the objective does, and the generation
        counts each time with its weight.
        """
        if not self._spores:
            return
        listed: list[dict[str, Any]] = [{"spore": label} for label in self._spores]
        for key, name in (("cost", "cost"), ("capacities", "flow_cap"), ("generation", "flow_out")):
            variable = self._solution.variables.get(name)
            if variable is None:
                continue
            array = LabeledArray.read(variable, self._solution)
            if _SPORES not in array:
                continue
            for entry, label in zip(listed, self._spores, strict=True):
                entry[key] = _value_or_map(self._of_spore(name, array.select(_SPORES, label)))
        self._results.details["spores"] = listed
        self._results.warnings.append(solutions_of_spores(len(self._spores)))

    def _of_spore(self, name: str, array: LabeledArray) -> LabeledArray:
        """Reduce a variable of one of the SPORES to what the document reports of it."""
        if name == "cost":
            if _COSTS in array:
                array = array.scale(_COSTS, self._cost_weights(array.labels[_COSTS]))
            return array.sum(_NODES, _TECHS, _COSTS, _TIME)
        if name == "flow_cap":
            return array.max(_CARRIERS)
        if _TIME in array:
            array = array.scale(_TIME, self._weights(len(array.labels[_TIME])))
        return array.sum(_TIME)


def _by(array: LabeledArray, *dims: str) -> list[tuple[tuple[str, ...], float]]:
    """Return the elements of `array` with their labels in the order of `dims`."""
    missing = [dim for dim in dims if dim not in array]
    if missing or len(dims) != len(array.dims):
        raise ExtractionError(
            f"an array has the dimensions {', '.join(array.dims) or 'none'};"
            f" expected are {', '.join(dims)}"
        )
    order = [array.dims.index(dim) for dim in dims]
    return [(tuple(labels[axis] for axis in order), value) for labels, value in array.items()]


def _value_or_map(array: LabeledArray) -> Any:
    if not array.dims:
        return None if np.isnan(array.values) else float(array.values)
    return {join(*labels): value for labels, value in array.items()}


def _ends(
    technology: str,
    origins: dict[str, str],
    destinations: dict[str, str],
    capacity: LabeledArray | None,
    flow_out: LabeledArray,
) -> tuple[str, str] | None:
    """Return the two nodes that a transmission technology connects."""
    if technology in origins and technology in destinations:
        return origins[technology], destinations[technology]
    for array in (capacity, flow_out):
        if array is None or technology not in array.labels.get(_TECHS, ()):
            continue
        defined = array.select(_TECHS, technology).absolute()
        defined = defined.sum(*(dim for dim in defined.dims if dim != _NODES))
        nodes = [labels[0] for labels, _ in defined.items()]
        if len(nodes) == 2:
            return nodes[0], nodes[1]
    return None
