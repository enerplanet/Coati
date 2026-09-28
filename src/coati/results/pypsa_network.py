"""A PyPSA network as its file describes it.

PyPSA writes a network as a set of tables. Every kind of component, such as
the generators, has a table of attributes with one row for each component, and
one table of time series for each attribute that varies with time. The two
formats PyPSA exports to store the same tables in different ways:

* `export_to_netcdf` writes a variable for each attribute:
  `generators_p_nom` over the dimension `generators_i`, and
  `generators_t_p` over `snapshots` and `generators_t_p_i`.
* `export_to_hdf5` writes each table with pandas: `/generators` and
  `/generators_t/p`. The columns of a table of time series are named by the
  positions of the components in the table of attributes.

`read_network` reads either into a `Network`, the form the
extractor works on.

Two properties of the files shape this module. PyPSA stores only the
attributes that differ from their defaults, so a component reports the default
of an attribute that the file lacks (`Component.numbers`). And a table of
time series holds only the components whose attribute varies with time, so a
series falls back to the attribute of the component
(`Component.varying`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Final

import numpy as np

from coati import cf
from coati.errors import ExtractionError
from coati.labeled import finite, numbers_of, texts_of
from coati.model import Dataset, Group, Variable
from coati.readers import pytables

__all__ = ["Component", "Network", "read_network"]

_SNAPSHOTS: Final = "snapshots"
_SCENARIO: Final = "scenario"
_INDEX: Final = "_i"
_SERIES: Final = "_t_"

#: The weightings of the snapshots that PyPSA knows.
WEIGHTINGS: Final = ("objective", "generators", "stores")

_INSTANT: Final = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$")


@dataclass
class Component:
    """The components of one kind, such as the generators.

    Attributes:
        names: The name of each component.
        static: The attributes, each with one value for each component:
            numbers, truth values or texts.
        series: The attributes that vary with time, each with one row for
            each snapshot and one column for each component; `NaN` in the
            column of a component whose attribute does not vary.
    """

    names: list[str] = field(default_factory=list)
    static: dict[str, np.ndarray[Any, Any]] = field(default_factory=dict)
    series: dict[str, np.ndarray[Any, Any]] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.names)

    def numbers(self, attribute: str, default: float) -> np.ndarray[Any, Any]:
        """Return the attribute as numbers, `default` where the file has none."""
        stored = self.static.get(attribute)
        if stored is None or stored.dtype.kind not in "biuf":
            return np.full(len(self), default, dtype=np.float64)
        values = stored.astype(np.float64)
        return np.where(np.isnan(values), default, values)

    def texts(self, attribute: str, default: str = "") -> list[str]:
        """Return the attribute as texts, `default` where the file has none."""
        stored = self.static.get(attribute)
        if stored is None:
            return [default] * len(self)
        return [default if item is None or item == "" else str(item) for item in stored.tolist()]

    def has(self, attribute: str) -> bool:
        """Tell whether the file has the attribute, for all components or as time series."""
        return attribute in self.static or attribute in self.series

    def flow(self, attribute: str, snapshots: int) -> np.ndarray[Any, Any]:
        """Return a result that varies with time, zero where the file has none."""
        stored = self.series.get(attribute)
        if stored is None:
            return np.zeros((snapshots, len(self)))
        return finite(stored)

    def varying(self, attribute: str, default: float, snapshots: int) -> np.ndarray[Any, Any]:
        """Return a parameter at each snapshot: its time series or else its one value."""
        constant = np.broadcast_to(self.numbers(attribute, default), (snapshots, len(self)))
        stored = self.series.get(attribute)
        if stored is None:
            return np.array(constant)
        return np.where(np.isnan(stored), constant, stored)


@dataclass
class Network:
    """A PyPSA network, or one scenario of a stochastic network.

    Attributes:
        name: The name of the network.
        objective: The value of the objective function; `None` if the
            network has not been optimised.
        objective_constant: The part of the cost that the objective leaves out.
        timestamps: The snapshots: instants as ISO 8601 text, or what else
            the network uses to name them.
        periods: The investment period of each snapshot, for a network with several.
        weightings: How much each snapshot counts, by the name of the weighting.
        components: The components, by the name of their table.
        scenarios: The weight of each scenario of a stochastic network.
    """

    name: str | None = None
    objective: float | None = None
    objective_constant: float | None = None
    timestamps: list[Any] = field(default_factory=list)
    periods: list[Any] | None = None
    weightings: dict[str, np.ndarray[Any, Any]] = field(default_factory=dict)
    components: dict[str, Component] = field(default_factory=dict)
    scenarios: dict[str, float] | None = None

    @property
    def snapshots(self) -> int:
        """The number of snapshots."""
        return len(self.timestamps)

    def component(self, table: str) -> Component:
        """Return the components of the table `table`; none if the file has no such table."""
        return self.components.get(table) or Component()

    def weighting(self, name: str) -> np.ndarray[Any, Any]:
        """Return how much each snapshot counts; one unless the file says otherwise."""
        stored = self.weightings.get(name)
        if stored is None or stored.shape != (self.snapshots,):
            return np.ones(self.snapshots)
        return finite(stored, nan=1.0)


def read_network(dataset: Dataset) -> list[Network]:
    """Read the network that `dataset` holds.

    Returns:
        The network; for a stochastic network, one network for each scenario,
        each with the weights of all scenarios.

    Raises:
        ExtractionError: The file does not hold the tables of a network.
    """
    if dataset.format == "hdf5":
        return [_Hdf5Reader(dataset).read()]
    return _NetcdfReader(dataset).read()


def _timestamp(value: Any) -> Any:
    """Return a label of a snapshot: an instant as ISO 8601 text, anything else as it is."""
    if isinstance(value, str) and _INSTANT.match(value):
        text = value.replace(" ", "T")
        return text if text.count(":") == 2 else text + ":00"
    return value


def _labels(variable: Variable) -> list[Any]:
    """Read the labels of the snapshots or of the periods."""
    decoded = cf.decode(variable)
    if decoded.values.dtype.kind in "iu":
        return [int(item) for item in decoded.values.ravel().tolist()]
    if decoded.values.dtype.kind == "f":
        return [float(item) for item in decoded.values.ravel().tolist()]
    return [_timestamp(text) for text in texts_of(variable)]


def _values(variable: Variable) -> np.ndarray[Any, Any]:
    """Read an attribute: numbers in double precision or texts."""
    decoded = cf.decode(variable)
    if decoded.values.dtype.kind in "biuf":
        return numbers_of(variable)
    texts = np.empty(decoded.values.size, dtype=object)
    texts[:] = texts_of(variable)
    return texts.reshape(decoded.values.shape)


class _NetcdfReader:
    """Reads the variables that `export_to_netcdf` writes."""

    def __init__(self, dataset: Dataset) -> None:
        self._dataset = dataset
        self._tables = sorted(
            name[: -len(_INDEX)]
            for name in dataset.dimensions
            if name.endswith(_INDEX) and _SERIES not in name
        )

    def read(self) -> list[Network]:
        if _SNAPSHOTS not in self._dataset.dimensions and not self._tables:
            raise ExtractionError(f"{self._dataset.source}: the file holds no tables of a network")
        scenarios = self._scenarios()
        if scenarios is None:
            return [self._network(None, None)]
        return [self._network(position, scenarios) for position in range(len(scenarios))]

    def _scenarios(self) -> dict[str, float] | None:
        names = self._dataset.variables.get(_SCENARIO)
        if names is None or _SCENARIO not in self._dataset.dimensions:
            return None
        labels = [text or str(position) for position, text in enumerate(texts_of(names))]
        weights = self._dataset.variables.get("scenario_weight")
        if weights is None or weights.shape != (len(labels),):
            return dict.fromkeys(labels, 1.0 / len(labels))
        return dict(zip(labels, numbers_of(weights).tolist(), strict=True))

    def _network(self, scenario: int | None, scenarios: dict[str, float] | None) -> Network:
        attributes = self._dataset.attributes
        network = Network(scenarios=scenarios)
        name = attributes.get("network_name")
        network.name = name if isinstance(name, str) and name else None
        network.objective = _number(attributes, "network__objective", "network_objective")
        network.objective_constant = _number(
            attributes, "network__objective_constant", "network_objective_constant"
        )
        self._read_snapshots(network)
        for table in self._tables:
            network.components[table] = self._component(table, scenario, network.snapshots)
        return network

    def _read_snapshots(self, network: Network) -> None:
        variables = self._dataset.variables
        dimension = self._dataset.dimensions.get(_SNAPSHOTS)
        length = dimension.size if dimension is not None else 0
        for name in ("snapshots_timestep", "snapshots_snapshot", _SNAPSHOTS):
            variable = variables.get(name)
            if variable is not None and variable.shape == (length,):
                network.timestamps = _labels(variable)
                break
        else:
            network.timestamps = list(range(length))
        periods = variables.get("snapshots_period")
        if periods is not None and periods.shape == (length,):
            network.periods = _labels(periods)
        for name in WEIGHTINGS:
            variable = variables.get(f"snapshots_{name}")
            if variable is not None and variable.shape == (length,):
                network.weightings[name] = numbers_of(variable)

    def _component(self, table: str, scenario: int | None, snapshots: int) -> Component:
        index = self._dataset.variables.get(table + _INDEX)
        names = [text or "" for text in texts_of(index)] if index is not None else []
        component = Component(names=names)
        positions = {name: position for position, name in enumerate(names)}
        for name, variable in self._dataset.variables.items():
            if not variable.dimensions or not name.startswith(table + "_"):
                continue
            last = variable.dimensions[-1]
            if last == table + _INDEX and name != last:
                values = _one_scenario(_values(variable), variable.dimensions, scenario)
                if values.shape == (len(names),):
                    component.static[name[len(table) + 1 :]] = values
            elif last == name + _INDEX and name.startswith(table + _SERIES):
                attribute = name[len(table) + len(_SERIES) :]
                series = self._series(variable, scenario, positions, snapshots)
                if series is not None:
                    component.series[attribute] = series
        return component

    def _series(
        self,
        variable: Variable,
        scenario: int | None,
        positions: dict[str, int],
        snapshots: int,
    ) -> np.ndarray[Any, Any] | None:
        """Read time series into one column for each component of the table."""
        columns = self._dataset.variables.get(variable.name + _INDEX)
        if columns is None or variable.dimensions[0] != _SNAPSHOTS:
            return None
        stored = _one_scenario(numbers_of(variable), variable.dimensions, scenario)
        if stored.ndim != 2 or stored.shape[0] != snapshots:
            return None
        series = np.full((snapshots, len(positions)), np.nan)
        for column, name in enumerate(texts_of(columns)):
            if name in positions:
                series[:, positions[name]] = stored[:, column]
        return series


def _one_scenario(
    values: np.ndarray[Any, Any], dimensions: tuple[str | None, ...], scenario: int | None
) -> np.ndarray[Any, Any]:
    """Return the part of `values` that belongs to one scenario."""
    if _SCENARIO not in dimensions:
        return values
    return np.asarray(np.take(values, scenario or 0, axis=dimensions.index(_SCENARIO)))


def _number(attributes: dict[str, Any], *names: str) -> float | None:
    for name in names:
        value = attributes.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and np.isfinite(value):
            return float(value)
    return None


class _Hdf5Reader:
    """Reads the tables that `export_to_hdf5` writes."""

    def __init__(self, dataset: Dataset) -> None:
        self._dataset = dataset

    def read(self) -> Network:
        groups = self._dataset.groups
        snapshots = groups.get(_SNAPSHOTS)
        if snapshots is None or not pytables.is_frame(snapshots):
            raise ExtractionError(f"{self._dataset.source}: the file holds no tables of a network")
        network = Network()
        self._read_network(network, groups.get("network"))
        self._read_snapshots(network, pytables.read_frame(snapshots))
        for name, group in groups.items():
            if pytables.is_frame(group) and name not in (
                _SNAPSHOTS,
                "network",
                "investment_periods",
            ):
                network.components[name] = self._component(group, groups.get(name + "_t"), network)
        return network

    def _read_network(self, network: Network, group: Group | None) -> None:
        if group is None or not pytables.is_frame(group):
            return
        frame = pytables.read_frame(group)
        if len(frame):
            name = frame.index[0]
            network.name = str(name) if name not in (None, "") else None
        network.objective = _cell(frame, "_objective", "objective")
        network.objective_constant = _cell(frame, "_objective_constant", "objective_constant")

    def _read_snapshots(self, network: Network, frame: pytables.Frame) -> None:
        for name in ("timestep", "snapshot"):
            column = frame.column(name)
            if column is not None:
                network.timestamps = _column_labels(column)
                break
        else:
            network.timestamps = list(range(len(frame)))
        periods = frame.column("period")
        if periods is not None:
            network.periods = _column_labels(periods)
        for name in WEIGHTINGS:
            column = frame.column(name)
            if column is not None and column.dtype.kind in "iuf":
                network.weightings[name] = column.astype(np.float64)

    def _component(self, group: Group, series: Group | None, network: Network) -> Component:
        frame = pytables.read_frame(group)
        names = frame.column("name")
        if names is None:
            raise ExtractionError(f"{group.path}: the table has no column of names")
        component = Component(names=[str(name) for name in names.tolist()])
        for attribute, column in frame.columns.items():
            if attribute != "name" and isinstance(attribute, str):
                component.static[attribute] = _column_values(column)
        for attribute, table in (series.groups if series is not None else {}).items():
            if pytables.is_frame(table):
                stored = self._series(pytables.read_frame(table), len(component), network.snapshots)
                if stored is not None:
                    component.series[attribute] = stored
        return component

    def _series(
        self, frame: pytables.Frame, components: int, snapshots: int
    ) -> np.ndarray[Any, Any] | None:
        if len(frame) != snapshots:
            return None
        series = np.full((snapshots, components), np.nan)
        for position, column in frame.columns.items():
            if isinstance(position, int) and 0 <= position < components:
                series[:, position] = column.astype(np.float64)
        return series


def _cell(frame: pytables.Frame, *names: str) -> float | None:
    """Return the number in the first row of the first of the columns `names`."""
    for name in names:
        column = frame.column(name)
        if column is not None and column.size and column.dtype.kind in "iuf":
            value = float(column[0])
            return value if np.isfinite(value) else None
    return None


def _column_values(column: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    if column.dtype.kind in "biuf":
        return column.astype(np.float64)
    return column


def _column_labels(column: np.ndarray[Any, Any]) -> list[Any]:
    if column.dtype.kind == "M":
        instants = np.datetime_as_string(column.astype("datetime64[s]")).astype(object)
        instants[np.isnat(column)] = None
        return list(instants.tolist())
    if column.dtype.kind in "iu":
        return [int(item) for item in column.tolist()]
    return [_timestamp(item) for item in column.tolist()]
