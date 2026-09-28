"""Results of Calliope 0.6.

Calliope 0.6 writes one group. Its arrays do not have one dimension for each
of location, technology and carrier but *sets* whose labels join them:
`energy_cap` is defined over `loc_techs` with labels such as
`region1::ccgt`, `carrier_prod` over `loc_tech_carriers_prod` with labels
such as `region1::ccgt::power`. A transmission technology carries the
location at the other end of the link in its name: `ac_transmission:region2`
at `region1` is the end at `region1` of the link to `region2`.

The configuration and the record of the run are attributes of the file, some of
them YAML. In SPORES mode the results have a further dimension `spores`, of
which the document reports the first.

How each key of the document follows from the file is described in the
documentation under *Frameworks*.
"""

from __future__ import annotations

from typing import Any, Final

import numpy as np

from coati import yamltext
from coati.errors import ExtractionError
from coati.frameworks import Framework
from coati.labeled import LabeledArray, finite, labels_of, texts_of, weights_of
from coati.model import Dataset
from coati.results.document import (
    SEPARATOR,
    Results,
    join,
    net_flows,
    solutions_of_spores,
    succeeded,
)
from coati.results.options import ExtractOptions

__all__ = ["extract"]

_COSTS: Final = "costs"
_TIME: Final = "timesteps"
_TECHS: Final = "techs"
_SPORES: Final = "spores"

_DEMAND: Final = "demand"
_TRANSMISSION: Final = "transmission"

# What separates a transmission technology from the location at the other end of the link.
_REMOTE: Final = ":"


def extract(dataset: Dataset, framework: Framework, options: ExtractOptions) -> Results:
    """Make the results of a file of Calliope 0.6.

    Raises:
        ExtractionError: A variable has other dimensions than Calliope gives it.
    """
    return _Extractor(dataset, framework, options).run()


def _split(label: str) -> tuple[str, str, str]:
    """Split the label of a set into location, technology and carrier."""
    parts = label.split(SEPARATOR)
    if len(parts) == 1:
        return "", parts[0], ""
    return parts[0], parts[1], parts[2] if len(parts) > 2 else ""


def _base(technology: str) -> str:
    """Return a technology without the location at the other end of its link."""
    return technology.split(_REMOTE, 1)[0]


class _Extractor:
    def __init__(self, dataset: Dataset, framework: Framework, options: ExtractOptions) -> None:
        self._dataset = dataset
        self._options = options
        self._run_config = dataset.attributes.get("run_config")
        self._spores: tuple[str, ...] = ()
        self._parents: dict[str, str] = {}
        self._results = Results(framework, "", False)

    def run(self) -> Results:
        results = self._results
        self._describe_run()
        self._parents = self._read_parents()
        coordinate = self._dataset.variables.get(_TIME)
        if coordinate is not None:
            results.timestamps = texts_of(coordinate)
            results.weights = self._weights(coordinate.shape[0])
        produced = self._array("carrier_prod")
        self._capacities()
        self._generation(produced)
        self._transmission(produced)
        self._demand()
        self._unmet_demand()
        self._costs()
        self._technologies(produced)
        self._coordinates()
        self._list_spores()
        results.finish()
        return results

    # -- reading ----------------------------------------------------------------------------

    def _array(self, name: str) -> LabeledArray | None:
        """Read a variable, reduced to the first of the SPORES."""
        variable = self._dataset.variables.get(name)
        if variable is None:
            return None
        array = LabeledArray.read(variable, self._dataset)
        if _SPORES in array:
            self._spores = array.labels[_SPORES]
            array = array.select(_SPORES, self._spores[0])
        return array

    def _set_of(self, array: LabeledArray, name: str) -> str:
        """Return the dimension of `array` that is a set of locations and technologies."""
        sets = [dim for dim in array.dims if dim not in (_TIME, _COSTS)]
        if len(sets) != 1:
            raise ExtractionError(
                f"/{name} has the dimensions {', '.join(array.dims)};"
                " expected is one set of locations and technologies"
            )
        return sets[0]

    def _rows(self, name: str, array: LabeledArray) -> list[tuple[str, np.ndarray[Any, Any]]]:
        """Return the time series of `array` for each label of its set."""
        if _TIME not in array:
            raise ExtractionError(f"/{name} has no dimension {_TIME}")
        dim = self._set_of(array, name)
        return [(label, array.select(dim, label).values) for label in array.labels[dim]]

    def _weights(self, length: int) -> np.ndarray[Any, Any]:
        """Return the weight of each time: how often the model counts it."""
        return weights_of(self._dataset.variables.get("timestep_weights"), length)

    def _texts(self, name: str) -> dict[str, str]:
        """Read a text for each technology, where there is one."""
        variable = self._dataset.variables.get(name)
        if variable is None or variable.dimensions != (_TECHS,):
            return {}
        labels = labels_of(self._dataset, _TECHS, variable.shape[0])
        return {
            label: text
            for label, text in zip(labels, texts_of(variable), strict=True)
            if text is not None
        }

    def _read_parents(self) -> dict[str, str]:
        """Return the abstract technology that each technology inherits from."""
        chains = self._texts("inheritance")
        parents = {name: chain.split(".")[-1] for name, chain in chains.items()}
        coordinate = self._dataset.variables.get(_TECHS)
        for name in texts_of(coordinate) if coordinate is not None else []:
            if name is not None and name not in parents and _base(name) in parents:
                parents[name] = parents[_base(name)]
        return parents

    def _is(self, technology: str, parent: str) -> bool:
        known = self._parents.get(technology) or self._parents.get(_base(technology))
        if known is not None:
            return known == parent
        if parent == _TRANSMISSION:
            return _REMOTE in technology
        return parent == _DEMAND and _DEMAND in technology.lower()

    # -- the parts of the document ----------------------------------------------------------

    def _describe_run(self) -> None:
        results = self._results
        attributes = self._dataset.attributes
        solved = any(name in self._dataset.variables for name in ("energy_cap", "carrier_prod"))
        condition = attributes.get("termination_condition")
        if not isinstance(condition, str) or not condition:
            condition = "unknown" if solved else "not_solved"
        results.termination_condition = condition
        results.success = solved and succeeded(condition)
        results.model_name = yamltext.scalar(attributes.get("model_config"), "name")
        results.solver = yamltext.scalar(self._run_config, "solver")
        mode = yamltext.scalar(self._run_config, "mode")
        if mode is not None:
            results.details["mode"] = mode
        value = attributes.get("objective_function_value")
        if isinstance(value, (int, float)) and np.isfinite(value):
            results.objective_function_value = float(value)
        if not solved:
            results.warnings.append("the file holds no results: the model has not been solved")

    def _capacities(self) -> None:
        for name, target in (
            ("energy_cap", self._results.capacities),
            ("storage_cap", self._results.storage_capacities),
        ):
            array = self._array(name)
            if array is None:
                continue
            self._set_of(array, name)
            for (label,), value in array.items():
                target[label] = value

    def _generation(self, produced: LabeledArray | None) -> None:
        if produced is None:
            return
        rows = self._rows("carrier_prod", produced)
        weights = self._weights(len(produced.labels[_TIME]))
        for label, series in rows:
            if np.isnan(series).all():
                continue
            self._results.generation[label] = float(np.nansum(series * weights))
            technology = _split(label)[1]
            if not self._is(technology, _TRANSMISSION) and not self._is(technology, _DEMAND):
                self._results.add_dispatch(technology, series)

    def _transmission(self, produced: LabeledArray | None) -> None:
        if produced is None:
            return
        arrivals: dict[tuple[str, str], np.ndarray[Any, Any]] = {}
        for label, series in self._rows("carrier_prod", produced):
            destination, technology, _ = _split(label)
            if _REMOTE not in technology or not self._is(technology, _TRANSMISSION):
                continue
            origin = technology.split(_REMOTE, 1)[1]
            arriving = finite(series)
            known = arrivals.get((origin, destination))
            arrivals[origin, destination] = arriving if known is None else known + arriving
        self._results.transmission_flow = net_flows(arrivals)

    def _demand(self) -> None:
        consumed = self._array("carrier_con")
        if consumed is None:
            return
        rows = self._rows("carrier_con", consumed)
        weights = self._weights(len(consumed.labels[_TIME]))
        total: np.ndarray[Any, Any] | None = None
        for label, series in rows:
            location, technology, _ = _split(label)
            if not self._is(technology, _DEMAND):
                continue
            magnitude = np.abs(finite(series))
            total = magnitude if total is None else total + magnitude
            energy = float((magnitude * weights).sum())
            if energy > 0:
                by_location = self._results.demand_by_location
                by_location[location] = by_location.get(location, 0.0) + energy
        self._results.demand_timeseries = total

    def _unmet_demand(self) -> None:
        unmet = self._array("unmet_demand")
        if unmet is None or _TIME not in unmet:
            return
        weights = self._weights(len(unmet.labels[_TIME]))
        total = np.zeros(len(unmet.labels[_TIME]))
        for label, series in self._rows("unmet_demand", unmet):
            shortfall = np.maximum(finite(series), 0.0)
            total += shortfall
            energy = float((shortfall * weights).sum())
            if energy > 0:
                location = label.split(SEPARATOR)[0]
                by_location = self._results.unmet_demand_by_location
                by_location[location] = by_location.get(location, 0.0) + energy
        self._results.unmet_demand_timeseries = total

    def _costs(self) -> None:
        cost = self._array("cost")
        if cost is None:
            return
        if _COSTS in cost:
            cost = cost.scale(_COSTS, self._cost_weights(cost.labels[_COSTS]))
        total = cost.sum(_COSTS, _TIME)
        self._set_of(total, "cost")
        for (label,), value in total.items():
            location, technology, _ = _split(label)
            self._results.add_cost(location, technology, value)
        if np.isfinite(total.values).any():
            self._results.objective = float(np.nansum(total.values))

    def _cost_weights(self, classes: tuple[str, ...]) -> np.ndarray[Any, Any]:
        """Return the weight of each class of cost in the objective.

        The configuration of the run lists the classes that the objective
        counts. A class that it does not list has the weight zero; without the
        list, every class has the weight one.
        """
        path = ("objective_options", "cost_class")
        if not yamltext.exists(self._run_config, *path):
            return np.ones(len(classes))
        weights = np.zeros(len(classes))
        for position, name in enumerate(classes):
            text = yamltext.scalar(self._run_config, *path, name)
            try:
                weights[position] = float(text) if text is not None else 0.0
            except ValueError:
                weights[position] = 0.0
        return weights

    def _technologies(self, produced: LabeledArray | None) -> None:
        names = self._texts("names") if self._options.labels else {}
        colors = self._texts("colors") if self._options.labels else {}
        carriers = self._output_carriers(produced)
        for technology, parent in self._parents.items():
            base = _base(technology)
            entry = {"parent": parent, "carrier_out": carriers.get(technology, "")}
            for key, texts in (("display_name", names), ("color", colors)):
                text = texts.get(technology) or texts.get(base)
                if text is not None:
                    entry[key] = text
            self._results.tech_metadata[technology] = entry

    def _output_carriers(self, produced: LabeledArray | None) -> dict[str, str]:
        """Return the carrier that each technology puts out, the primary one if it has several."""
        carriers: dict[str, str] = {}
        primary = self._dataset.variables.get("lookup_primary_loc_tech_carriers_out")
        labels = [label for label in texts_of(primary) if label] if primary is not None else []
        if produced is not None:
            labels.extend(produced.labels[self._set_of(produced, "carrier_prod")])
        for label in labels:
            _, technology, carrier = _split(label)
            if carrier:
                carriers.setdefault(technology, carrier)
        return carriers

    def _coordinates(self) -> None:
        variable = self._dataset.variables.get("loc_coordinates")
        if variable is None or set(variable.dimensions) != {"coordinates", "locs"}:
            return
        positions = LabeledArray.read(variable, self._dataset)
        if not {"lat", "lon"} <= set(positions.labels["coordinates"]):
            return  # the locations are given in a plane, not on the globe
        latitude = positions.select("coordinates", "lat")
        longitude = positions.select("coordinates", "lon")
        east = dict(longitude.items())
        for labels, north in latitude.items():
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
        for key, name in (
            ("cost", "cost"),
            ("capacities", "energy_cap"),
            ("generation", "carrier_prod"),
        ):
            variable = self._dataset.variables.get(name)
            if variable is None:
                continue
            array = LabeledArray.read(variable, self._dataset)
            if _SPORES not in array:
                continue
            for entry, label in zip(listed, self._spores, strict=True):
                entry[key] = self._of_spore(name, array.select(_SPORES, label))
        self._results.details["spores"] = listed
        self._results.warnings.append(solutions_of_spores(len(self._spores)))

    def _of_spore(self, name: str, array: LabeledArray) -> Any:
        """Reduce a variable of one of the SPORES to what the document reports of it."""
        if name == "cost":
            if _COSTS in array:
                array = array.scale(_COSTS, self._cost_weights(array.labels[_COSTS]))
            total = array.sum(*array.dims)
            return None if np.isnan(total.values) else float(total.values)
        if _TIME in array:
            array = array.scale(_TIME, self._weights(len(array.labels[_TIME]))).sum(_TIME)
        return {join(*labels): value for labels, value in array.items()}
