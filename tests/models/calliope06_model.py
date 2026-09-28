"""A Calliope 0.6 model with every kind of technology that the results document knows.

Calliope 0.6 needs Python 3.9 or older, so this module does without what newer
versions of Python have added.
"""

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
model:
    name: Coati test model
    calliope_version: 0.6.10
    timeseries_data_path: timeseries
    subset_time: ['2005-01-01', '2005-01-01']

run:
    solver: {solver}
    ensure_feasibility: true
    bigM: 1e6
    zero_threshold: 1e-10
    mode: plan
    objective_options.cost_class: {{monetary: 1}}

techs:
    pv:
        essentials:
            name: Solar photovoltaics
            color: '#F9D956'
            parent: supply
            carrier_out: power
        constraints:
            resource: file=pv.csv:per_capacity
            resource_unit: energy_per_cap
            energy_cap_max: 300
            lifetime: 25
        costs:
            monetary:
                interest_rate: 0.10
                energy_cap: 80
    gas:
        essentials:
            name: Gas turbine
            color: '#E4AB97'
            parent: supply
            carrier_out: power
        constraints:
            resource: inf
            energy_eff: 0.5
            energy_cap_max: 200
            lifetime: 25
        costs:
            monetary:
                interest_rate: 0.10
                energy_cap: 30
                om_con: 20
            emissions:
                om_prod: 0.4
    battery:
        essentials:
            name: Battery
            color: '#3B61E3'
            parent: storage
            carrier: power
        constraints:
            energy_cap_max: 100
            storage_cap_max: 400
            energy_eff: 0.95
            storage_loss: 0
            lifetime: 15
        costs:
            monetary:
                interest_rate: 0.10
                storage_cap: 5
    boiler:
        essentials:
            name: Electric boiler
            color: '#8E2999'
            parent: conversion
            carrier_in: power
            carrier_out: heat
        constraints:
            energy_cap_max: 100
            energy_eff: 0.9
            lifetime: 20
        costs:
            monetary:
                interest_rate: 0.10
                energy_cap: 10
    demand_power:
        essentials:
            name: Power demand
            color: '#072486'
            parent: demand
            carrier: power
    demand_heat:
        essentials:
            name: Heat demand
            color: '#660507'
            parent: demand
            carrier: heat
    line:
        essentials:
            name: Power line
            color: '#8465A9'
            parent: transmission
            carrier: power
        constraints:
            energy_eff: 0.98
            energy_cap_max: 150
            lifetime: 40
        costs:
            monetary:
                interest_rate: 0.10
                energy_cap: 4

locations:
    north:
        coordinates: {{lat: 49.0, lon: 11.0}}
        techs:
            pv:
    south:
        coordinates: {{lat: 48.0, lon: 12.0}}
        techs:
            gas:
            battery:
            boiler:
            demand_power:
                constraints:
                    resource: file=demand.csv:power
            demand_heat:
                constraints:
                    resource: file=demand.csv:heat

links:
    north,south:
        techs:
            line:

overrides:
    spores:
        run.mode: spores
        run.spores_options:
            score_cost_class: spores_score
            slack_cost_group: systemwide_cost_max
            slack: 0.2
            spores_number: 2
            objective_cost_class: {{monetary: 0, spores_score: 1}}
        run.objective_options.cost_class: {{monetary: 1, spores_score: 0}}
        group_constraints:
            systemwide_cost_max.cost_max.monetary: 1e10
        techs.pv.costs.spores_score: {{energy_cap: 0, interest_rate: 1}}
        techs.gas.costs.spores_score: {{energy_cap: 0, interest_rate: 1}}
        techs.battery.costs.spores_score: {{energy_cap: 0, interest_rate: 1}}
        techs.boiler.costs.spores_score: {{energy_cap: 0, interest_rate: 1}}
        techs.line.costs.spores_score: {{energy_cap: 0, interest_rate: 1}}
"""


def write_model(directory: Path, solver: str = "cbc") -> Path:
    """Write the definition of the model and its time series; return the path of the model."""
    series = directory / "timeseries"
    series.mkdir(parents=True, exist_ok=True)
    stamps = [f"2005-01-01 {hour:02d}:00:00" for hour in range(HOURS)]
    sun = [max(0.0, math.sin((hour - 6) / 12 * math.pi)) for hour in range(HOURS)]
    power = [-(60 + 20 * math.sin((hour - 6) / 24 * 2 * math.pi)) for hour in range(HOURS)]
    rows = [f"{stamp},{value:.6f}" for stamp, value in zip(stamps, sun)]  # noqa: B905
    (series / "pv.csv").write_text("\n".join([",per_capacity", *rows]) + "\n")
    rows = [f"{stamp},{value:.6f},-10.0" for stamp, value in zip(stamps, power)]  # noqa: B905
    (series / "demand.csv").write_text("\n".join([",power,heat", *rows]) + "\n")
    model = directory / "model.yaml"
    model.write_text(MODEL.format(solver=solver))
    return model


def solve(directory: Path, solver: str = "cbc", mode: str = "plan") -> Any:
    """Build the model in ``directory`` and solve it, to plan or to find SPORES."""
    import calliope

    calliope.set_log_verbosity("ERROR", include_solver_output=False)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        scenario = "spores" if mode == "spores" else None
        model = calliope.Model(str(write_model(directory, solver)), scenario=scenario)
        model.run()
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
    cost = results["cost"].sel(costs="monetary")
    produced = results["carrier_prod"]
    found: dict[str, Any] = {
        "objective": float(cost.sum()),
        "timestamps": [str(stamp)[:19] for stamp in results["timesteps"].values],
        "capacities": _entries(results["energy_cap"]),
        "storage_capacities": _entries(results["storage_cap"]),
        "generation": _entries((produced * weights).sum("timesteps", min_count=1)),
        "dispatch": {},
        "costs": {},
    }
    parents = {
        str(name): str(chain).split(".")[-1]
        for name, chain in inputs["inheritance"].to_series().items()
    }
    for label in produced["loc_tech_carriers_prod"].values:
        technology = str(label).split("::")[1]
        if ":" in technology or parents.get(technology) == "demand":
            continue
        series = produced.sel(loc_tech_carriers_prod=label).fillna(0).values
        known = found["dispatch"].get(technology)
        found["dispatch"][technology] = [
            float(value) + (known[position] if known else 0.0)
            for position, value in enumerate(series)
        ]
    consumed = results["carrier_con"]
    demand = [0.0] * len(found["timestamps"])
    by_location: dict[str, float] = {}
    for label in consumed["loc_tech_carriers_con"].values:
        location, technology = str(label).split("::")[:2]
        if parents.get(technology) != "demand":
            continue
        series = abs(consumed.sel(loc_tech_carriers_con=label)).fillna(0)
        demand = [known + float(value) for known, value in zip(demand, series.values)]  # noqa: B905
        by_location[location] = by_location.get(location, 0.0) + float((series * weights).sum())
    found["demand_timeseries"] = demand
    found["demand_by_location"] = by_location
    south = produced.sel(loc_tech_carriers_prod="south::line:north::power").fillna(0)
    north = produced.sel(loc_tech_carriers_prod="north::line:south::power").fillna(0)
    found["transmission_flow"] = {"north::south": [float(value) for value in south - north]}
    for label, value in cost.to_series().dropna().items():
        technology = str(label).split("::")[1]
        found["costs"][technology] = found["costs"].get(technology, 0.0) + float(value)
    return found


def _entries(array: Any) -> dict[str, float]:
    """Return the elements of an array that have a value, by their labels."""
    return {str(label): float(value) for label, value in array.to_series().dropna().items()}


def build(directory: Path, solver: str = "cbc") -> dict[str, Path]:
    """Solve the model and write it to ``directory``.

    Returns:
        The files that have been written, by a name for what they hold.
    """
    directory.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for mode, name in (("plan", "model"), ("spores", "spores")):
        target = directory / f"{name}.nc"
        target.unlink(missing_ok=True)
        described = directory / f"{name}.facts.json"
        with tempfile.TemporaryDirectory() as work, warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = solve(Path(work), solver, mode)
            model.to_netcdf(str(target))
            described.write_text(json.dumps(facts(model), indent=1) + "\n")
        written[target.name] = target
        written[described.name] = described
    return written


if __name__ == "__main__":
    for name, path in build(Path(sys.argv[1])).items():
        sys.stdout.write(f"{name}: {path} ({path.stat().st_size} bytes)\n")
