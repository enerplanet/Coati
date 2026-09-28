"""Files made for a test, in the layouts that the frameworks write.

The numbers are small and chosen so that every figure of a results document
can be checked by hand; the modules of the tests state what they expect. All
models have the same shape: photovoltaics at the location ``a``, a load and a
battery at ``b``, a line between them, three hours from 2030-01-01, of which
the second counts twice.

The netCDF files are written with the netCDF library, as the frameworks do
through xarray, and follow the conventions of xarray: a truth value is a byte
with the attribute ``dtype``, a time is a number with ``units``.
"""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any

import h5py
import netCDF4
import numpy as np

NAN = float("nan")
TIME_UNITS = "hours since 2030-01-01 00:00:00"
CALENDAR = "proleptic_gregorian"
TIMESTAMPS = ["2030-01-01T00:00:00", "2030-01-01T01:00:00", "2030-01-01T02:00:00"]
WEIGHTS = [1.0, 2.0, 1.0]


# -- netCDF -----------------------------------------------------------------------------------


def write_netcdf(path: Path, content: dict[str, Any], file_format: str = "NETCDF4") -> Path:
    """Write a netCDF file from a description.

    Args:
        path: The file to write.
        content: The root group. A group is a dictionary with the optional
            keys ``attributes``, ``dimensions`` (sizes by name; ``None`` for
            an unlimited one), ``variables`` and ``groups``. A variable is a
            tuple of the names of its dimensions, its values and, optionally,
            its attributes.
        file_format: The format, as the netCDF library names it.
    """
    with netCDF4.Dataset(path, "w", format=file_format) as dataset:
        _fill(dataset, content)
    return path


def _fill(group: Any, content: dict[str, Any]) -> None:
    for name, value in content.get("attributes", {}).items():
        group.setncattr(name, value)
    for name, size in content.get("dimensions", {}).items():
        group.createDimension(name, size)
    for name, described in content.get("variables", {}).items():
        dims, values, *rest = described
        _variable(group, name, tuple(dims), values, rest[0] if rest else {})
    for name, child in content.get("groups", {}).items():
        _fill(group.createGroup(name), child)


def _variable(
    group: Any, name: str, dims: tuple[str, ...], values: Any, attributes: dict[str, Any]
) -> None:
    data = np.asarray(values)
    attributes = dict(attributes)
    fill = attributes.pop("_FillValue", None)
    if data.dtype.kind in "UO":
        variable = group.createVariable(name, str, dims)
        for index, text in np.ndenumerate(data):
            variable[index] = text
    else:
        if data.dtype.kind == "b":
            data = data.astype("i1")
            attributes.setdefault("dtype", "bool")
        elif data.dtype.kind == "f" and fill is None:
            fill = NAN
        variable = group.createVariable(name, data.dtype, dims, fill_value=fill)
        variable.set_auto_maskandscale(False)
        variable[...] = data
    for key, value in attributes.items():
        variable.setncattr(key, value)


def _time(count: int = 3) -> tuple[tuple[str, ...], Any, dict[str, Any]]:
    return ("timesteps",), np.arange(count), {"units": TIME_UNITS, "calendar": CALENDAR}


# -- Calliope 0.7 -----------------------------------------------------------------------------

NODES = ["a", "b"]
TECHS = ["pv", "load", "battery", "line"]

CALLIOPE07_CONFIG = """\
init:
  name: Synthetic model
  calliope_version: {version}
  mode: {mode}
build:
  objective: min_cost_optimisation
solve:
  solver: highs
  zero_threshold: 1e-10
"""

CALLIOPE07_RUNTIME = """\
applied_overrides: ''
{initialised}scenario:
timings:
  solve_start: 1790551491.667643
termination_condition: {condition}
"""


def _at(values: dict[tuple[int, ...], Any], shape: tuple[int, ...]) -> np.ndarray[Any, Any]:
    """Return an array that has the given values and is ``NaN`` elsewhere."""
    array = np.full(shape, NAN)
    for index, value in values.items():
        array[index] = value
    return array


def calliope07(
    path: Path,
    *,
    version: str = "0.7.0",
    condition: str = "optimal",
    spores: int = 0,
    operate: bool = False,
    solved: bool = True,
    links: bool = True,
) -> Path:
    """Write a file as Calliope 0.7 does.

    Args:
        path: The file to write.
        version: The version the file states. A preview, such as
            ``0.7.0.dev7``, states it in the record of the run, a release in
            the configuration.
        condition: The termination condition the file states.
        spores: The number of SPORES; none if zero. The second and further
            SPORES hold the numbers of the first, times their position plus one.
        operate: Whether the file is that of a model in operate mode, whose
            capacities are inputs and whose costs have one entry for each time.
        solved: Whether the file has results.
        links: Whether the inputs name the ends of the line.
    """
    coordinates = {
        "nodes": (("nodes",), NODES),
        "techs": (("techs",), TECHS),
        "carriers": (("carriers",), ["power"]),
        "costs": (("costs",), ["monetary", "emissions"]),
        "timesteps": _time(),
    }
    dimensions = {"nodes": 2, "techs": 4, "carriers": 1, "costs": 2, "timesteps": 3}
    capacity = _at(
        {(0, 0, 0): 10, (0, 3, 0): 5, (1, 1, 0): 8, (1, 2, 0): 4, (1, 3, 0): 5}, (2, 4, 1)
    )
    inputs: dict[str, Any] = {
        "base_tech": (("techs",), ["supply", "demand", "storage", "transmission"]),
        "name": (("techs",), ["Solar", "Load", "Battery", "Line"]),
        "color": (("techs",), ["#F9D956", "#072486", "#3B61E3", "#8465A9"]),
        "carrier_out": (
            ("nodes", "techs", "carriers"),
            np.array([[[1], [0], [0], [1]], [[0], [0], [1], [1]]], dtype=bool),
        ),
        "definition_matrix": (
            ("nodes", "techs", "carriers"),
            np.array([[[1], [0], [0], [1]], [[0], [1], [1], [1]]], dtype=bool),
        ),
        "latitude": (("nodes",), [50.0, 51.0]),
        "longitude": (("nodes",), [10.0, 11.0]),
        "timestep_weights": (("timesteps",), WEIGHTS),
        "objective_cost_weights": (("costs",), [1.0, 0.5]),
        **coordinates,
    }
    if links:
        inputs["link_from"] = (("techs",), ["<NA>", "<NA>", "<NA>", "a"], {"_FillValue": "<NA>"})
        inputs["link_to"] = (("techs",), ["<NA>", "<NA>", "<NA>", "b"], {"_FillValue": "<NA>"})
    if operate:
        inputs["flow_cap"] = (("techs",), [10.0, 8.0, 4.0, 5.0])
    flow_out = _at(
        {(0, 0, 0): [6, 8, 4], (1, 2, 0): [0, 1, 2], (1, 3, 0): [3, 4, 2], (0, 3, 0): [0, 0, 1]},
        (2, 4, 1, 3),
    )
    flow_in = _at({(1, 1, 0): [5, 6, 7], (1, 2, 0): [1, 0, 0]}, (2, 4, 1, 3))
    cost = _at({(0, 0): [100, 0], (1, 2): [20, 4], (0, 3): [3, 0], (1, 3): [3, 0]}, (2, 4, 2))
    unmet = np.array([[[0, 0, 0]], [[0, 0.5, 0]]], dtype=float)
    results: dict[str, Any] = {
        "flow_out": (("nodes", "techs", "carriers", "timesteps"), flow_out),
        "flow_in": (("nodes", "techs", "carriers", "timesteps"), flow_in),
        "unmet_demand": (("nodes", "carriers", "timesteps"), unmet),
        "storage_cap": (("nodes", "techs"), _at({(1, 2): 16}, (2, 4))),
    }
    if operate:
        shifted = np.full((3, 2, 4, 2), NAN)
        shifted[0] = cost
        results["cost"] = (("timesteps", "nodes", "techs", "costs"), shifted)
        results["min_cost_optimisation"] = (("timesteps",), [127.0, NAN, NAN])
    else:
        results["flow_cap"] = (("nodes", "techs", "carriers"), capacity)
        results["cost"] = (("nodes", "techs", "costs"), cost)
        results["min_cost_optimisation"] = ((), 127.0)
    result_dimensions = dict(dimensions)
    if spores:
        results = _repeat(results, spores)
        result_dimensions = {"spores": spores, **dimensions}
        coordinates = {"spores": (("spores",), np.arange(spores)), **coordinates}
    preview = "dev" in version or "rc" in version
    initialised = f"calliope_version_initialised: {version}\n" if preview else ""
    mode = "spores" if spores else "operate" if operate else "base"
    content: dict[str, Any] = {
        "groups": {
            "inputs": {"dimensions": dimensions, "variables": inputs},
            "attrs": {
                "attributes": {
                    "config": CALLIOPE07_CONFIG.format(version=version, mode=mode),
                    "runtime": CALLIOPE07_RUNTIME.format(
                        initialised=initialised, condition=condition
                    ),
                }
            },
        }
    }
    if solved:
        content["groups"]["results"] = {
            "dimensions": result_dimensions,
            "variables": {**results, **coordinates},
        }
    return write_netcdf(path, content)


def _repeat(variables: dict[str, Any], count: int) -> dict[str, Any]:
    """Give every variable a leading dimension of SPORES."""
    repeated = {}
    for name, (dims, values) in variables.items():
        data = np.asarray(values, dtype=float)
        stacked = np.stack([data * (position + 1) for position in range(count)])
        repeated[name] = (("spores", *dims), stacked)
    return repeated


# -- Calliope 0.6 -----------------------------------------------------------------------------

CALLIOPE06_RUN = """\
backend: pyomo
mode: plan
objective_options:
  cost_class:
    monetary: 1
  sense: minimize
solver: cbc
"""


def calliope06(
    path: Path,
    *,
    condition: str = "optimal",
    planar: bool = False,
    spores: int = 0,
    without: tuple[str, ...] = (),
    run: str | None = None,
) -> Path:
    """Write a file as Calliope 0.6 does.

    Args:
        path: The file to write.
        condition: The termination condition the file states; none if empty.
        planar: Whether the locations are given in a plane instead of on the globe.
        spores: The number of SPORES; none if zero. The second and further
            SPORES hold the numbers of the first, times their position plus one.
        without: The variables that the file lacks.
        run: The configuration of the run, in place of the usual one.
    """
    sets = {
        "loc_techs": ["a::pv", "b::battery", "b::load", "a::line:b", "b::line:a"],
        "loc_techs_store": ["b::battery"],
        "loc_techs_cost": ["a::pv", "b::battery", "a::line:b", "b::line:a"],
        "loc_tech_carriers_prod": [
            "a::pv::power",
            "b::battery::power",
            "b::line:a::power",
            "a::line:b::power",
        ],
        "loc_tech_carriers_con": ["b::load::power", "b::battery::power"],
        "loc_carriers": ["a::power", "b::power"],
        "techs": ["pv", "battery", "load", "line", "line:a", "line:b"],
        "locs": ["a", "b"],
        "carriers": ["power"],
        "costs": ["monetary", "emissions"],
        "coordinates": ["x", "y"] if planar else ["lat", "lon"],
    }
    variables: dict[str, Any] = {name: ((name,), labels) for name, labels in sets.items()}
    variables.update(
        {
            "timesteps": _time(),
            "energy_cap": (("loc_techs",), [10.0, 4.0, 8.0, 5.0, 5.0]),
            "storage_cap": (("loc_techs_store",), [16.0]),
            "carrier_prod": (
                ("loc_tech_carriers_prod", "timesteps"),
                [[6.0, 8, 4], [0, 1, 2], [3, 4, 2], [0, 0, 1]],
            ),
            "carrier_con": (
                ("loc_tech_carriers_con", "timesteps"),
                [[-5.0, -6, -7], [-1, 0, 0]],
            ),
            "cost": (("costs", "loc_techs_cost"), [[100.0, 20, 3, 3], [0, 4, 0, 0]]),
            "unmet_demand": (("loc_carriers", "timesteps"), [[0.0, 0, 0], [0, 0.5, 0]]),
            "inheritance": (("techs",), ["supply", "storage", "demand", "transmission", "", ""]),
            "names": (("techs",), ["Solar", "Battery", "Load", "Line", "", ""]),
            "colors": (("techs",), ["#F9D956", "#3B61E3", "#072486", "#8465A9", "", ""]),
            "loc_coordinates": (("coordinates", "locs"), [[50.0, 51.0], [10.0, 11.0]]),
            "timestep_weights": (("timesteps",), WEIGHTS),
        }
    )
    dimensions = {name: len(labels) for name, labels in sets.items()}
    dimensions["timesteps"] = 3
    run = CALLIOPE06_RUN if run is None else run
    if spores:
        solved = ("energy_cap", "storage_cap", "carrier_prod", "carrier_con", "cost")
        variables.update(_repeat({name: variables[name] for name in solved}, spores))
        variables["spores"] = (("spores",), np.arange(spores))
        dimensions["spores"] = spores
        run = run.replace("mode: plan", "mode: spores")
    for name in without:
        del variables[name]
    attributes = {
        "calliope_version": "0.6.10",
        "objective_function_value": np.array([127.0]),
        "model_config": "name: Synthetic model\ncalliope_version: 0.6.10\n",
        "run_config": run,
    }
    if condition:
        attributes["termination_condition"] = condition
    return write_netcdf(
        path, {"attributes": attributes, "dimensions": dimensions, "variables": variables}
    )


# -- PyPSA ------------------------------------------------------------------------------------

#: The tables of the network: the names of the components and their attributes.
PYPSA_TABLES: dict[str, dict[str, Any]] = {
    "buses": {
        "name": ["a::power", "b::power"],
        "carrier": ["power", "power"],
        "x": [10.0, 11.0],
        "y": [50.0, 51.0],
    },
    "generators": {
        "name": ["pv@a", "b::gas", "shed"],
        "bus": ["a::power", "b::power", "b::power"],
        "carrier": ["solar", "gas", "load_shedding"],
        "p_nom_opt": [10.0, 20.0, 100.0],
        "p_nom_extendable": [True, False, False],
        "capital_cost": [5.0, 2.0, 0.0],
        "marginal_cost": [0.0, 30.0, 1000.0],
    },
    "loads": {"name": ["load"], "bus": ["b::power"]},
    "links": {
        "name": ["line"],
        "bus0": ["a::power"],
        "bus1": ["b::power"],
        "p_nom_opt": [5.0],
        "p_nom_extendable": [True],
        "capital_cost": [4.0],
        "efficiency": [0.5],
    },
    "storage_units": {
        "name": ["battery"],
        "bus": ["b::power"],
        "p_nom_opt": [4.0],
        "max_hours": [4.0],
        "cyclic_state_of_charge": [True],
    },
}

#: What the network states as its objective, and the part of the cost that PyPSA leaves out
#: of it. Together they are the cost of the capacities that were decided, 50 for the sun and
#: 20 for the line, of the operation, 130 for the gas, and of the demand that is not met, 1000.
PYPSA_OBJECTIVE = 1190.0
PYPSA_CONSTANT = 10.0

#: The time series of the network: the names of the components and their values.
PYPSA_SERIES: dict[str, dict[str, tuple[list[str], list[list[float]]]]] = {
    "generators": {
        "p": (["pv@a", "b::gas", "shed"], [[6, 1, 0], [8, 0, 0.5], [4, 2, 0]]),
        "marginal_cost": (["b::gas"], [[30], [40], [50]]),
    },
    "loads": {"p": (["load"], [[5], [6], [7]])},
    "links": {
        "p0": (["line"], [[4], [6], [-2]]),
        "p1": (["line"], [[-2], [-3], [1]]),
    },
    "storage_units": {"p": (["battery"], [[0], [1], [-2]])},
}


def pypsa_netcdf(
    path: Path, *, version: str = "1.2.4", solved: bool = True, snapshots: str = "time"
) -> Path:
    """Write a file as ``export_to_netcdf`` of PyPSA does.

    Args:
        path: The file to write.
        version: The version the file states. Versions before 0.26 name the
            attribute of the objective with one underscore.
        solved: Whether the network has been optimised.
        snapshots: How the snapshots are named: ``time`` for instants,
            ``text`` for instants written as text, ``number`` for positions.
    """
    objective = "network_objective" if version.startswith("0.25") else "network__objective"
    attributes: dict[str, Any] = {
        "network_name": "synthetic",
        "network_pypsa_version": version,
        "network_srid": np.array([4326]),
    }
    if solved:
        attributes[objective] = np.array([PYPSA_OBJECTIVE])
        attributes[objective + "_constant"] = np.array([PYPSA_CONSTANT])
    dimensions: dict[str, Any] = {"snapshots": 3}
    variables: dict[str, Any] = {"snapshots": (("snapshots",), np.arange(3))}
    if snapshots == "time":
        labels: Any = (np.arange(3), {"units": TIME_UNITS, "calendar": CALENDAR})
    elif snapshots == "text":
        labels = ([stamp.replace("T", " ") for stamp in TIMESTAMPS], {})
    else:
        labels = (np.arange(3), {})
    variables["snapshots_snapshot"] = (("snapshots",), *labels)
    for name in ("objective", "generators", "stores"):
        variables[f"snapshots_{name}"] = (("snapshots",), WEIGHTS)
    for table, columns in PYPSA_TABLES.items():
        index = f"{table}_i"
        dimensions[index] = len(columns["name"])
        variables[index] = ((index,), columns["name"])
        for attribute, values in columns.items():
            optimised = attribute.endswith("_opt")
            if attribute != "name" and (solved or not optimised):
                variables[f"{table}_{attribute}"] = ((index,), values)
    for table, series in PYPSA_SERIES.items() if solved else ():
        for attribute, (names, values) in series.items():
            index = f"{table}_t_{attribute}_i"
            dimensions[index] = len(names)
            variables[index] = ((index,), names)
            variables[f"{table}_t_{attribute}"] = (("snapshots", index), np.array(values, float))
    return write_netcdf(
        path, {"attributes": attributes, "dimensions": dimensions, "variables": variables}
    )


def pypsa_hdf5(path: Path, *, version: str = "1.2.4") -> Path:
    """Write a file as ``export_to_hdf5`` of PyPSA does, the network of :func:`pypsa_netcdf`."""
    with h5py.File(path, "w") as file:
        file.attrs["PYTABLES_FORMAT_VERSION"] = np.bytes_("2.1")
        write_frame(
            file.create_group("network"),
            ["synthetic"],
            {
                "pypsa_version": [version],
                "_objective": [PYPSA_OBJECTIVE],
                "_objective_constant": [PYPSA_CONSTANT],
                "srid": [4326],
            },
        )
        instants = np.array(TIMESTAMPS, dtype="datetime64[us]")
        write_frame(
            file.create_group("snapshots"),
            [0, 1, 2],
            {"snapshot": instants, "objective": WEIGHTS, "stores": WEIGHTS, "generators": WEIGHTS},
        )
        for table, columns in PYPSA_TABLES.items():
            write_frame(file.create_group(table), list(range(len(columns["name"]))), columns)
        for table, series in PYPSA_SERIES.items():
            group = file.create_group(f"{table}_t")
            positions = {name: place for place, name in enumerate(PYPSA_TABLES[table]["name"])}
            for attribute, (names, values) in series.items():
                data = np.array(values, dtype=float)
                columns = {positions[name]: data[:, place] for place, name in enumerate(names)}
                write_frame(group.create_group(attribute), [0, 1, 2], columns)
    return path


def write_frame(group: Any, index: list[Any], columns: dict[Any, Any]) -> None:
    """Write a table as pandas does in the table format of PyTables.

    The columns of one type share a block; the names of the columns of a
    block are an attribute of the table, pickled.
    """
    blocks: dict[str, list[tuple[Any, np.ndarray[Any, Any]]]] = {}
    for name, values in columns.items():
        data = np.asarray(values)
        if data.dtype.kind in "UO":
            data = np.char.encode(data.astype(str), "utf-8")
        kind = "bytes" if data.dtype.kind == "S" else data.dtype.name
        blocks.setdefault(kind, []).append((name, data))
    labels = np.asarray(index)
    if labels.dtype.kind in "UO":
        labels = np.char.encode(labels.astype(str), "utf-8")
    fields: list[tuple[str, Any, tuple[int, ...]]] = [("index", labels.dtype, ())]
    parts: dict[str, np.ndarray[Any, Any]] = {"index": labels}
    attributes: dict[str, Any] = {
        "index_kind": "string" if labels.dtype.kind == "S" else "integer",
    }
    for position, (kind, members) in enumerate(blocks.items()):
        block = f"values_block_{position}"
        stacked = np.stack([data for _, data in members], axis=1)
        stored = stacked.astype("u1") if kind == "bool" else stacked
        if stored.dtype.kind == "M":
            attributes[f"{block}_dtype"] = str(stored.dtype)
            stored = stored.astype("i8")
        else:
            attributes[f"{block}_dtype"] = (
                kind if kind != "bytes" else f"bytes{stored.itemsize * 8}"
            )
        fields.append((block, stored.dtype, (len(members),)))
        parts[block] = stored
        attributes[f"{block}_kind"] = pickle.dumps([name for name, _ in members], protocol=0)
    table = np.zeros(len(labels), dtype=np.dtype(fields))
    for name, values in parts.items():
        table[name] = values
    dataset = group.create_dataset("table", data=table)
    for name, value in attributes.items():
        dataset.attrs[name] = np.bytes_(value) if isinstance(value, (str, bytes)) else value
    group.attrs["pandas_type"] = np.bytes_("frame_table")
    group.attrs["nan_rep"] = np.bytes_("nan")


# -- AdOpT-NET0 -------------------------------------------------------------------------------

#: What one investment period costs: the technologies 100, the network 11, what is
#: bought 130, less 1 for what is sold.
ADOPT_COST = 240.0

ADOPT_SUMMARY: dict[str, Any] = {
    "total_npv": ADOPT_COST,
    "total_cost": ADOPT_COST,
    "cost_tecs": 100.0,
    "cost_netws": 11.0,
    "cost_imports": 130.0,
    "cost_exports": -1.0,
    "carbon_cost": 0.0,
    "carbon_revenue": 0.0,
    "violation_cost": 0.0,
    "solver_status": "optimal",
    "objective": "costs",
    "case": "synthetic",
    "pareto_point": -1,
    "monte_carlo_run": -1,
    "time_stamp": "/home/someone/results/20260928-1",
}


def adopt_net0(
    path: Path,
    *,
    periods: tuple[str, ...] = ("period1",),
    capitalised: bool = False,
    typical_days: int = 0,
    alike: bool = False,
    summary: dict[str, Any] | None = None,
) -> Path:
    """Write a file as AdOpT-NET0 does.

    Args:
        path: The file to write.
        periods: The investment periods. The numbers of the second and
            further periods are those of the first, times their position plus one.
        capitalised: Whether the names of the groups at the top start with a capital.
        typical_days: The method by which the model aggregates time into typical
            days, as AdOpT-NET0 numbers them; zero if it does not. With the
            method 1 the three times of the file are those of the typical days,
            which stand for four times, the second of them twice. With the
            method 2 the file has the series of the whole modelled time.
        alike: Whether every period holds the results of the last, except for the
            design of the networks, as AdOpT-NET0 0.1.10 writes them.
        summary: Figures that replace or add to those of the summary.
    """
    names = {
        name: name.capitalize() if capitalised else name
        for name in ("summary", "topology", "design", "operation", "k_means_specs")
    }
    factors = [position + 1.0 for position in range(len(periods))]
    total = {name: ADOPT_COST * sum(factors) for name in ("total_npv", "total_cost")}
    with h5py.File(path, "w") as file:
        figures = file.create_group(names["summary"])
        for name, value in {**ADOPT_SUMMARY, **total, **(summary or {})}.items():
            figures.create_dataset(name, data=value)
        topology = file.create_group(names["topology"])
        topology.create_dataset("nodes", data=["a", "b"])
        topology.create_dataset("carriers", data=["power"])
        topology.create_dataset("periods", data=list(periods))
        clustering = file.create_group(names["k_means_specs"])
        for period, factor in zip(periods, factors, strict=True):
            _adopt_period(file, names, period, factors[-1] if alike else factor, factor)
            if typical_days:
                specs = clustering.create_group(period)
                specs.create_dataset("factors", data=[1, 2, 1] if typical_days == 1 else [3])
                specs.create_dataset(
                    "sequence", data=[1, 2, 2, 3] if typical_days == 1 else [1] * 3
                )
    return path


def _adopt_period(
    file: Any, names: dict[str, str], period: str, factor: float, network: float
) -> None:
    """Write one period, all amounts times ``factor``, those of the arcs times ``network``."""
    design = file.require_group(f"{names['design']}/nodes/{period}")
    wind = design.create_group("a/Wind")
    wind.create_dataset("technology", data=["Wind"])
    wind.create_dataset("size", data=[2.0 * factor])
    wind.create_dataset("rated_power", data=1.5)
    for name, value in (("capex_tot", 60.0), ("opex_fixed_tot", 6.0), ("opex_variable", 4.0)):
        wind.create_dataset(name, data=[value * factor])
    battery = design.create_group("b/Battery")
    battery.create_dataset("size", data=[8.0 * factor])
    for name, value in (("capex_tot", 30.0), ("opex_fixed_tot", 0.0), ("opex_variable", 0.0)):
        battery.create_dataset(name, data=[value * factor])

    arcs = file.require_group(f"{names['design']}/networks/{period}/cable")
    for arc, origin, destination, variable in (("ab", "a", "b", 1.0), ("ba", "b", "a", 0.0)):
        sized = arcs.create_group(arc)
        sized.create_dataset("network", data="cable")
        sized.create_dataset("fromNode", data=origin)
        sized.create_dataset("toNode", data=destination)
        sized.create_dataset("size", data=5.0 * network)
        sized.create_dataset("capex", data=10.0 * network)
        sized.create_dataset("opex_fixed", data=[0.0])
        sized.create_dataset("opex_variable", data=variable * network)

    operation = file.require_group(f"{names['operation']}/technology_operation/{period}")
    operation.create_dataset("a/Wind/power_output", data=np.array([3.0, 2, 1]) * factor)
    operation.create_dataset("a/Wind/cap_factor", data=[0.5, 0.4, 0.2])
    operation.create_dataset("b/Battery/power_input", data=np.array([1.0, 0, 0]) * factor)
    operation.create_dataset("b/Battery/power_output", data=np.array([-0.0, 1, 0]) * factor)
    operation.create_dataset("b/Battery/storage_level", data=np.array([1.0, 0, 0]) * factor)

    balance = file.require_group(f"{names['operation']}/energy_balance/{period}")
    for node, flows in (
        ("a", {"demand": [0, 0, 0], "import": [2.0, 3, 4], "import_price": [10, 10, 20],
               "export": [0.0, 0, 1e-12], "export_price": [0, 0, 0]}),
        ("b", {"demand": [4, 5, 4], "import": [0.0, 0, 0], "import_price": [0, 0, 0],
               "export": [0.5, 0, 0], "export_price": [2, 2, 2]}),
    ):  # fmt: skip
        for name, values in flows.items():
            scaled = np.array(values) * (1.0 if name.endswith("price") else factor)
            balance.create_dataset(f"{node}/power/{name}", data=scaled)

    flows = file.require_group(f"{names['operation']}/networks/{period}/cable")
    flows.create_dataset("ab/flow", data=np.array([4.0, 4, 4]) * factor)
    flows.create_dataset("ab/losses", data=np.array([0.5, 0.5, 0.5]) * factor)
    flows.create_dataset("ba/flow", data=[0.0, 0, 0])
    flows.create_dataset("ba/losses", data=[0.0, 0, 0])
