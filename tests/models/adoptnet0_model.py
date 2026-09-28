"""An AdOpT-NET0 model that fills every group of the file of results.

Two nodes are joined by a network. The north has photovoltaics and wind
turbines and may buy and sell electricity, the south has the demand and
batteries, one of which exists already.

The model is solved in three variants: as it is, with typical days that stand
for the modelled time, and with two investment periods.
"""

from __future__ import annotations

import json
import math
import sys
import tempfile
import warnings
from pathlib import Path
from typing import Any

HOURS = 48
NODES = ("north", "south")
NETWORK = "electricitySimple"

#: The variants of the model: the investment periods, the days that are modelled and the
#: number of typical days that stand for them, none if zero.
VARIANTS: dict[str, dict[str, Any]] = {
    "base": {"periods": ("period1",), "days": 2, "typical": 0},
    "typical-days": {"periods": ("period1",), "days": 6, "typical": 2},
    "periods": {"periods": ("period1", "period2"), "days": 2, "typical": 0},
}


def demand_of(hours: int) -> list[float]:
    """Return the demand for electricity in the south at each hour."""
    return [40 + 15 * math.sin((hour - 6) / 24 * 2 * math.pi) for hour in range(hours)]


def write_model(
    directory: Path, results: Path, solver: str = "glpk", variant: str = "base"
) -> Path:
    """Write the input data of the model; return the folder that holds it."""
    import adopt_net0 as adopt
    import pandas as pd

    chosen = VARIANTS[variant]
    periods = list(chosen["periods"])
    data = directory / "input_data"
    data.mkdir(parents=True, exist_ok=True)
    results.mkdir(parents=True, exist_ok=True)
    adopt.create_optimization_templates(data)
    _edit(
        data / "Topology.json",
        nodes=list(NODES),
        carriers=["electricity"],
        investment_periods=periods,
        start_date="2025-06-01 00:00",
        end_date=f"2025-06-{chosen['days']:02d} 23:00",
        resolution="1h",
        investment_period_length=1,
    )
    config = json.loads((data / "ConfigModel.json").read_text())
    config["solveroptions"]["solver"]["value"] = solver
    config["reporting"]["save_path"]["value"] = str(results)
    config["reporting"]["save_summary_path"]["value"] = str(results)
    config["reporting"]["case_name"]["value"] = "coati"
    if chosen["typical"]:
        # The method 1 solves the typical days alone; the file then has their series.
        config["optimization"]["typicaldays"]["N"]["value"] = chosen["typical"]
        config["optimization"]["typicaldays"]["method"]["value"] = 1
    (data / "ConfigModel.json").write_text(json.dumps(config, indent=2))
    adopt.create_input_data_folder_template(data)

    places = pd.read_csv(data / "NodeLocations.csv", sep=";", index_col=0)
    places.loc["north", ["lon", "lat", "alt"]] = [11.0, 49.0, 300]
    places.loc["south", ["lon", "lat", "alt"]] = [12.0, 48.0, 400]
    places.to_csv(data / "NodeLocations.csv", sep=";")

    technologies = {
        "north": {"existing": {}, "new": ["Photovoltaic", "WindTurbine_Onshore_1500"]},
        "south": {"existing": {"Storage_Battery": 5}, "new": ["Storage_Battery"]},
    }
    networks = {"existing": [], "new": [NETWORK]}
    for period in periods:
        for node, listed in technologies.items():
            target = data / period / "node_data" / node / "Technologies.json"
            target.write_text(json.dumps(listed, indent=2))
        (data / period / "Networks.json").write_text(json.dumps(networks, indent=2))
    adopt.copy_technology_data(data)
    adopt.copy_network_data(data)
    for period in periods:
        _connect(data / period / "network_topology" / "new")
    _fill_carriers(data, periods, 24 * chosen["days"])
    _fill_climate(data, periods)
    return data


def _edit(path: Path, **values: object) -> None:
    content = json.loads(path.read_text())
    content.update(values)
    path.write_text(json.dumps(content, indent=2))


def _connect(topology: Path) -> None:
    """Join the two nodes in both directions."""
    import pandas as pd

    target = topology / NETWORK
    target.mkdir(parents=True, exist_ok=True)
    for name, value in (("connection", 1), ("distance", 120), ("size_max_arcs", 200)):
        table = pd.read_csv(topology / f"{name}.csv", sep=";", index_col=0)
        table.loc["north", "south"] = value
        table.loc["south", "north"] = value
        table.to_csv(target / f"{name}.csv", sep=";")


def _fill_carriers(data: Path, periods: list[str], hours: int) -> None:
    import adopt_net0 as adopt
    import pandas as pd

    adopt.fill_carrier_data(data, value_or_data=0)
    for position, period in enumerate(periods):
        # The demand of the second period is twice that of the first.
        demand = [value * (position + 1) for value in demand_of(hours)]
        adopt.fill_carrier_data(
            data,
            value_or_data=pd.DataFrame({"Demand": demand}),
            columns=["Demand"],
            carriers=["electricity"],
            nodes=["south"],
            investment_periods=[period],
        )
    for column, value in (
        ("Import limit", 35),
        ("Import price", 80),
        ("Import emission factor", 0.3),
        ("Export limit", 200),
        ("Export price", 5),
    ):
        adopt.fill_carrier_data(
            data, value_or_data=value, columns=[column], carriers=["electricity"], nodes=["north"]
        )


def _fill_climate(data: Path, periods: list[str]) -> None:
    """Write the weather as formulas of the hour, so that the model needs no download."""
    import pandas as pd

    for period, node in ((period, node) for period in periods for node in NODES):
        path = data / period / "node_data" / node / "ClimateData.csv"
        climate = pd.read_csv(path, sep=";", index_col=0)
        hours = range(len(climate))
        day = [max(0.0, math.sin((hour % 24 - 6) / 12 * math.pi)) for hour in hours]
        climate["ghi"] = [800 * light for light in day]
        climate["dni"] = [600 * light for light in day]
        climate["dhi"] = [200 * light for light in day]
        climate["temp_air"] = [15 + 8 * light for light in day]
        climate["rh"] = 60
        climate["ws10"] = [6 + 3 * math.sin(hour / 7) for hour in hours]
        climate.to_csv(path, sep=";")


def solve(directory: Path, solver: str = "glpk", variant: str = "base") -> Path:
    """Build the model in ``directory`` and solve it; return the file of results."""
    import adopt_net0 as adopt

    results = directory / "results"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        data = write_model(directory, results, solver, variant)
        hub = adopt.ModelHub()
        hub.read_data(data)
        hub.quick_solve()
    found = sorted(results.rglob("optimization_results.h5"))
    if len(found) != 1:
        raise RuntimeError(f"expected one file of results, found {len(found)}: not solved?")
    return found[0]


def facts(results: Path) -> dict[str, Any]:
    """Say what AdOpT-NET0 says about the solved model, in the terms of the results document.

    AdOpT-NET0 keeps nothing of a solved model but the file of results, so
    the facts are read from it, with the function AdOpT-NET0 offers for that,
    and checked against the figures of the summary, which AdOpT-NET0 computes
    from the model.
    """
    import adopt_net0 as adopt
    import h5py

    with h5py.File(results, "r") as file:
        summary = {key: _single(values) for (key,), values in _datasets(adopt, file["summary"])}
        design = dict(_datasets(adopt, file["design/nodes/period1"]))
        operation = dict(_datasets(adopt, file["operation/technology_operation/period1"]))
        balance = dict(_datasets(adopt, file["operation/energy_balance/period1"]))
        arcs = dict(_datasets(adopt, file[f"operation/networks/period1/{NETWORK}"]))
        networks = dict(_datasets(adopt, file[f"design/networks/period1/{NETWORK}"]))
    found: dict[str, Any] = {
        "objective": float(summary["total_npv"]),
        "capacities": {},
        "storage_capacities": {},
        "generation": {},
        "dispatch": {},
        "costs": {},
    }
    for (node, technology, name), values in design.items():
        if name != "size":
            continue
        size = _single(values)
        key = f"{node}::{technology}"
        if (node, technology, "storage_level") in operation:
            found["storage_capacities"][key] = size
            found["capacities"][key] = size
        else:
            found["capacities"][key] = size * _single(design[node, technology, "rated_power"])
        found["costs"][technology] = found["costs"].get(technology, 0.0) + sum(
            _single(design[node, technology, part])
            for part in ("capex_tot", "opex_fixed_tot", "opex_variable")
        )
        output = [float(value) for value in operation[node, technology, "electricity_output"]]
        found["generation"][f"{key}::electricity"] = sum(output)
        found["dispatch"][technology] = [max(value, 0.0) for value in output]
    bought = [float(value) for value in balance["north", "electricity", "import"]]
    found["generation"]["north::import_electricity::electricity"] = sum(bought)
    found["dispatch"]["import_electricity"] = bought
    found["costs"]["import_electricity"] = float(summary["cost_imports"])
    demand = [float(value) for value in balance["south", "electricity", "demand"]]
    found["demand_timeseries"] = demand
    found["demand_by_location"] = {"south": sum(demand)}
    southward = [
        float(flow) - float(loss)
        for flow, loss in zip(arcs["northsouth", "flow"], arcs["northsouth", "losses"], strict=True)
    ]
    northward = [
        float(flow) - float(loss)
        for flow, loss in zip(arcs["southnorth", "flow"], arcs["southnorth", "losses"], strict=True)
    ]
    found["transmission_flow"] = {
        "north::south": [there - back for there, back in zip(southward, northward, strict=True)]
    }
    # The network works in both directions: AdOpT-NET0 sizes both arcs alike and charges
    # the connection once. The document lets each of the two arcs bear half of the cost.
    for origin, destination in (("north", "south"), ("south", "north")):
        found["capacities"][f"{origin}::{NETWORK}:{destination}"] = _single(
            networks[f"{origin}{destination}", "size"]
        )
        found["costs"][f"{NETWORK}:{destination}"] = float(summary["cost_netws"]) / 2
    _check_summary(found, summary)
    return found


def facts_of_the_summary(results: Path, variant: str) -> dict[str, Any]:
    """Say what AdOpT-NET0 says about a variant of the model as a whole.

    The figures of the summary are computed by AdOpT-NET0 from the model, with
    the weight of each typical day and for all investment periods together.
    The demand is that of the input data. For a model of several periods it
    is stated for each of them under a key of its own, ``_demand_of_periods``,
    which is no key of the results document: what the file of AdOpT-NET0
    0.1.10 holds for a period is not what the model says about that period.
    """
    import adopt_net0 as adopt
    import h5py

    chosen = VARIANTS[variant]
    with h5py.File(results, "r") as file:
        summary = {key: _single(values) for (key,), values in _datasets(adopt, file["summary"])}
    demand = demand_of(24 * chosen["days"])
    found: dict[str, Any] = {"objective_function_value": float(summary["total_npv"])}
    if len(chosen["periods"]) == 1:
        found["objective"] = float(summary["total_npv"])
        found["demand_timeseries"] = demand
        found["demand_by_location"] = {"south": sum(demand)}
        found["costs"] = {"import_electricity": float(summary["cost_imports"])}
        found["details"] = {"typical_days": True}
    else:
        found["details"] = {"periods": list(chosen["periods"]), "period": chosen["periods"][0]}
        found["_demand_of_periods"] = {
            period: sum(demand) * (position + 1)
            for position, period in enumerate(chosen["periods"])
        }
    return found


def _datasets(adopt: Any, group: Any) -> Any:
    return adopt.extract_datasets_from_h5group(group).items()


def _single(values: Any) -> Any:
    value = values[0] if len(values) else None
    if isinstance(value, bytes):
        return value.decode()
    return float(value) if value is not None else None


def _check_summary(found: dict[str, Any], summary: dict[str, Any]) -> None:
    """Make sure that the facts add up to the figures that AdOpT-NET0 reports."""
    technologies = sum(
        cost
        for name, cost in found["costs"].items()
        if name != "import_electricity" and not name.startswith(NETWORK)
    )
    if not math.isclose(technologies, summary["cost_tecs"], rel_tol=1e-9, abs_tol=1e-6):
        raise RuntimeError(
            f"the technologies cost {technologies}, the summary says {summary['cost_tecs']}"
        )


def build(directory: Path, solver: str = "glpk") -> dict[str, Path]:
    """Solve the model and write its results to ``directory``.

    Returns:
        The files that have been written, by a name for what they hold.
    """
    directory.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for variant in VARIANTS:
        target = directory / f"{variant}.h5"
        described = directory / f"{variant}.facts.json"
        with tempfile.TemporaryDirectory() as work:
            target.write_bytes(solve(Path(work), solver, variant).read_bytes())
        found = facts(target) if variant == "base" else facts_of_the_summary(target, variant)
        described.write_text(json.dumps(found, indent=1) + "\n")
        written[target.name] = target
        written[described.name] = described
    return written


if __name__ == "__main__":
    for name, path in build(Path(sys.argv[1])).items():
        sys.stdout.write(f"{name}: {path} ({path.stat().st_size} bytes)\n")
