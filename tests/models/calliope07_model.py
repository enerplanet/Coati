"""A Calliope 0.7 model with every kind of technology that the results document knows."""

from __future__ import annotations

import json
import math
import sys
import tempfile
import warnings
from pathlib import Path
from typing import Any

HOURS = 24

MODEL = """\
config:
  init:
    name: Coati test model
    broadcast_input_data: true
    mode: {mode}
  build:
    ensure_feasibility: true
  solve:
    solver: {solver}
    zero_threshold: 1e-10{alternatives}

data_definitions:
  bigM: 1e6{slack}
  objective_cost_weights:
    data: [1, 0]
    index: [monetary, emissions]
    dims: costs
  cost_interest_rate:
    data: 0.10
    index: monetary
    dims: costs

techs:
  pv:
    name: Solar photovoltaics
    color: "#F9D956"
    base_tech: supply
    carrier_out: power
    flow_cap_max: 300
    lifetime: 25
    cost_flow_cap:
      data: 80
      index: monetary
      dims: costs
  gas:
    name: Gas turbine
    color: "#E4AB97"
    base_tech: supply
    carrier_out: power
    flow_out_eff: 0.5
    flow_cap_max: 200
    lifetime: 25
    cost_flow_cap:
      data: 30
      index: monetary
      dims: costs
    cost_flow_out:
      data: [40, 0.4]
      index: [monetary, emissions]
      dims: costs
  battery:
    name: Battery
    color: "#3B61E3"
    base_tech: storage
    carrier_in: power
    carrier_out: power
    flow_cap_max: 100
    storage_cap_max: 400
    flow_out_eff: 0.95
    flow_in_eff: 0.95
    storage_loss: 0
    lifetime: 15
    cost_storage_cap:
      data: 5
      index: monetary
      dims: costs
  boiler:
    name: Electric boiler
    color: "#8E2999"
    base_tech: conversion
    carrier_in: power
    carrier_out: heat
    flow_cap_max: 100
    flow_out_eff: 0.9
    lifetime: 20
    cost_flow_cap:
      data: 10
      index: monetary
      dims: costs
  demand_power:
    name: Power demand
    color: "#072486"
    base_tech: demand
    carrier_in: power
  demand_heat:
    name: Heat demand
    color: "#660507"
    base_tech: demand
    carrier_in: heat
  line:
    name: Power line
    color: "#8465A9"
    base_tech: transmission
    link_from: north
    link_to: south
    carrier_in: power
    carrier_out: power
    flow_out_eff: 0.98
    flow_cap_max: 150
    lifetime: 40
    cost_flow_cap:
      data: 4
      index: monetary
      dims: costs

nodes:
  north:
    latitude: 49.0
    longitude: 11.0
    techs:
      pv:
  south:
    latitude: 48.0
    longitude: 12.0
    techs:
      gas:
      battery:
      boiler:
      demand_power:
      demand_heat:

data_tables:
  time_series:
    {table}: time_series.csv
    rows: timesteps
    columns: [nodes, techs, {parameters}]
"""

# Calliope 0.7.0 names two keys of a data table differently than its previews.
RELEASE = {"table": "table", "parameters": "inputs"}
PREVIEW = {"table": "data", "parameters": "parameters"}

#: How many alternatives the SPORES mode looks for, and how much more they may cost.
SPORES = 2
SLACK = 0.2


def is_preview() -> bool:
    """Tell whether the installed Calliope is a preview of 0.7.0."""
    import calliope

    return "dev" in calliope.__version__ or "rc" in calliope.__version__


def write_model(directory: Path, solver: str = "cbc", mode: str = "base") -> Path:
    """Write the definition of the model and its time series; return the path of the model."""
    directory.mkdir(parents=True, exist_ok=True)
    names = PREVIEW if is_preview() else RELEASE
    lines = [
        "nodes,north,south,south",
        "techs,pv,demand_power,demand_heat",
        f"{names['parameters']},source_use_max,sink_use_equals,sink_use_equals",
        "timesteps,,,",
    ]
    for hour in range(HOURS):
        sun = max(0.0, math.sin((hour - 6) / 12 * math.pi))
        power = 60 + 20 * math.sin((hour - 6) / 24 * 2 * math.pi)
        lines.append(f"2005-01-01 {hour:02d}:00:00,{sun * 300:.6f},{power:.6f},10.0")
    (directory / "time_series.csv").write_text("\n".join(lines) + "\n")
    alternatives = slack = ""
    if mode == "spores":
        alternatives = f"\n    spores:\n      number: {SPORES}"
        slack = f"\n  spores_slack: {SLACK}"
    model = directory / "model.yaml"
    definition = MODEL.format(
        solver=solver, mode=mode, alternatives=alternatives, slack=slack, **names
    )
    model.write_text(definition)
    return model


def solve(directory: Path, solver: str = "cbc", mode: str = "base") -> Any:
    """Build the model in ``directory`` and solve it."""
    import calliope

    calliope.set_log_verbosity("ERROR", include_solver_output=False)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = _read(calliope, write_model(directory, solver, mode))
        model.build()
        model.solve()
    return model


def facts(model: Any) -> dict[str, Any]:
    """Say what Calliope says about the solved model, in the terms of the results document.

    Every number comes from ``model.results`` and ``model.inputs``, the
    datasets of xarray that Calliope offers. None of it is read from a file.
    """
    results, inputs = model.results, model.inputs
    if "spores" in results.dims:
        results = results.isel(spores=0)
    weights = inputs["timestep_weights"]
    classes = inputs["objective_cost_weights"]
    cost = (results["cost"] * classes).sum("costs", min_count=1)
    found: dict[str, Any] = {
        "objective": float(cost.sum()),
        "timestamps": [str(stamp)[:19] for stamp in results["timesteps"].values],
        "capacities": _entries(results["flow_cap"].max("carriers"), "nodes", "techs"),
        "storage_capacities": _entries(results["storage_cap"], "nodes", "techs"),
        "generation": _entries(
            (results["flow_out"] * weights).sum("timesteps", min_count=1),
            "nodes",
            "techs",
            "carriers",
        ),
        "dispatch": {},
        "costs": {},
    }
    kinds = inputs["base_tech"].to_series()
    for technology, kind in kinds.items():
        if kind in ("demand", "transmission"):
            continue
        series = results["flow_out"].sel(techs=technology).sum(["nodes", "carriers"])
        found["dispatch"][str(technology)] = [float(value) for value in series]
    demands = [name for name, kind in kinds.items() if kind == "demand"]
    consumed = abs(results["flow_in"].sel(techs=demands))
    found["demand_timeseries"] = [
        float(value) for value in consumed.sum(["nodes", "techs", "carriers"])
    ]
    found["demand_by_location"] = _entries(
        (consumed * weights).sum(["timesteps", "techs", "carriers"], min_count=1), "nodes"
    )
    arriving = results["flow_out"].sel(techs="line").sum("carriers")
    net = arriving.sel(nodes="south").fillna(0) - arriving.sel(nodes="north").fillna(0)
    found["transmission_flow"] = {"north::south": [float(value) for value in net]}
    for technology, value in cost.sum("nodes", min_count=1).to_series().dropna().items():
        found["costs"][str(technology)] = float(value)
    return found


def _entries(array: Any, *dims: str) -> dict[str, float]:
    """Return the elements of an array that have a value, by their labels joined with ``::``."""
    series = array.transpose(*dims).to_series().dropna()
    entries: dict[str, float] = {}
    for labels, value in series.items():
        key = labels if isinstance(labels, str) else "::".join(str(label) for label in labels)
        entries[key] = float(value)
    return entries


def _read(calliope: Any, definition: Path) -> Any:
    """Read a definition; the function for that has been renamed between versions."""
    for name in ("read_yaml", "Model"):
        reader = getattr(calliope, name, None)
        if reader is not None:
            try:
                return reader(str(definition))
            except TypeError:
                continue
    raise RuntimeError("this version of Calliope offers no way to read a definition")


def build(directory: Path, solver: str = "cbc") -> dict[str, Path]:
    """Solve the model and write it to ``directory``.

    Returns:
        The files that have been written, by a name for what they hold.
    """
    directory.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for mode, name in (("base", "model"), ("spores", "spores")):
        target = directory / f"{name}.nc"
        target.unlink(missing_ok=True)
        with tempfile.TemporaryDirectory() as work, warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = solve(Path(work), solver, mode)
            model.to_netcdf(target)
            described = directory / f"{name}.facts.json"
            described.write_text(json.dumps(facts(model), indent=1) + "\n")
        written[target.name] = target
        written[described.name] = described
    return written


if __name__ == "__main__":
    for name, path in build(Path(sys.argv[1])).items():
        sys.stdout.write(f"{name}: {path} ({path.stat().st_size} bytes)\n")
