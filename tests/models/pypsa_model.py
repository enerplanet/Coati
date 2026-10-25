"""A PyPSA network with every kind of component that the results document knows."""

from __future__ import annotations

import json
import math
import sys
import warnings
from pathlib import Path
from typing import Any

SNAPSHOTS = 24


def network(*, solve: bool = True) -> Any:
    """Build the network and, unless told otherwise, optimise it with HiGHS.

    Two locations exchange electricity over a link and a line. The north has
    sun and wind, the south a gas plant, a battery, a heat pump with a heat
    store, and the demand for electricity and heat.
    """
    import numpy as np
    import pandas as pd
    import pypsa

    hours = np.arange(SNAPSHOTS)
    sun = np.clip(np.sin((hours % 24 - 6) / 12 * np.pi), 0, None)
    wind = 0.4 + 0.3 * np.sin(hours / 7.0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        n = pypsa.Network(name="coati")
        n.set_snapshots(pd.date_range("2025-03-01", periods=SNAPSHOTS, freq="h"))
        n.snapshot_weightings.loc[:, :] = 2.0
        for carrier, emissions in (("electricity", 0.0), ("heat", 0.0), ("gas", 0.2)):
            n.add("Carrier", carrier, co2_emissions=emissions)
        n.add("Bus", "north::electricity", carrier="electricity", x=11.0, y=49.0)
        n.add("Bus", "south::electricity", carrier="electricity", x=12.0, y=48.0)
        n.add("Bus", "south::heat", carrier="heat", x=12.0, y=48.0)
        n.add(
            "Generator",
            "north::pv",
            bus="north::electricity",
            carrier="electricity",
            p_nom_extendable=True,
            capital_cost=40.0,
            p_max_pu=sun,
            p_nom_max=500.0,
        )
        n.add(
            "Generator",
            "wind@north",
            bus="north::electricity",
            carrier="electricity",
            p_nom_extendable=True,
            capital_cost=60.0,
            p_max_pu=wind,
        )
        n.add(
            "Generator",
            "gas",
            bus="south::electricity",
            carrier="gas",
            p_nom=200.0,
            marginal_cost=70.0 + 10.0 * np.cos(hours / 5.0),
            efficiency=0.5,
        )
        n.add(
            "Load",
            "demand",
            bus="south::electricity",
            p_set=60 + 20 * np.sin((hours - 6) / 24 * 2 * np.pi),
        )
        n.add("Load", "heat_demand", bus="south::heat", p_set=10.0)
        n.add(
            "Link",
            "cable",
            bus0="north::electricity",
            bus1="south::electricity",
            carrier="electricity",
            p_nom_extendable=True,
            capital_cost=5.0,
            efficiency=0.97,
            marginal_cost=0.1,
        )
        n.add(
            "Link",
            "heat_pump",
            bus0="south::electricity",
            bus1="south::heat",
            carrier="heat",
            p_nom_extendable=True,
            capital_cost=20.0,
            efficiency=3.0,
        )
        n.add(
            "StorageUnit",
            "battery",
            bus="south::electricity",
            carrier="electricity",
            p_nom_extendable=True,
            capital_cost=30.0,
            max_hours=4.0,
            efficiency_store=0.95,
            efficiency_dispatch=0.95,
            cyclic_state_of_charge=True,
            marginal_cost=0.2,
        )
        n.add(
            "Store",
            "heat_store",
            bus="south::heat",
            carrier="heat",
            e_nom_extendable=True,
            capital_cost=2.0,
            e_cyclic=True,
        )
        n.add(
            "Line",
            "overhead",
            bus0="north::electricity",
            bus1="south::electricity",
            x=0.1,
            r=0.01,
            s_nom=50.0,
            capital_cost=1.0,
            carrier="electricity",
        )
        if solve:
            status, condition = n.optimize(solver_name="highs")
            if (status, condition) != ("ok", "optimal"):
                raise RuntimeError(f"the network was not solved: {status}, {condition}")
    return n


def stochastic() -> Any:
    """Build and optimise a network with two scenarios of the price of gas."""
    import pandas as pd
    import pypsa

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        n = pypsa.Network(name="coati-stochastic")
        n.set_snapshots(pd.date_range("2025-03-01", periods=4, freq="h"))
        n.add("Carrier", "electricity")
        n.add("Bus", "hub::electricity", carrier="electricity")
        n.add(
            "Generator",
            "gas",
            bus="hub::electricity",
            carrier="electricity",
            p_nom=300.0,
            marginal_cost=50.0,
        )
        n.add(
            "Generator",
            "pv",
            bus="hub::electricity",
            carrier="electricity",
            p_nom_extendable=True,
            capital_cost=900.0,
            p_nom_max=200.0,
            p_max_pu=[0.0, 0.5, 1.0, 0.2],
        )
        n.add("Load", "demand", bus="hub::electricity", p_set=[100.0, 120.0, 110.0, 90.0])
        n.set_scenarios({"high": 0.25, "low": 0.75})
        n.generators.loc[("high", "gas"), "marginal_cost"] = 90.0
        n.generators.loc[("low", "gas"), "marginal_cost"] = 30.0
        status, condition = n.optimize(solver_name="highs")
        if (status, condition) != ("ok", "optimal"):
            raise RuntimeError(f"the network was not solved: {status}, {condition}")
    return n


def power_flow() -> Any:
    """Build an electrical network with a dispatch that is given, and solve its power flow.

    The grid feeds a town and a village at medium voltage through two
    transformers and a line, which form a ring. Photovoltaics in the south
    hold the voltage of their bus, a combined heat and power plant in the
    north runs at a set point, a battery charges and discharges by a
    schedule, and a cable feeds an island that balances itself. The power
    flow is linear first and then non-linear, as MEME runs it.
    """
    import numpy as np
    import pandas as pd
    import pypsa

    hours = np.arange(SNAPSHOTS)
    sun = np.clip(np.sin((hours % 24 - 6) / 12 * np.pi), 0, None)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        n = pypsa.Network(name="coati-power-flow")
        n.set_snapshots(pd.date_range("2025-03-01", periods=SNAPSHOTS, freq="h"))
        n.add("Bus", "grid::electricity", v_nom=110.0, x=11.0, y=49.0, v_mag_pu_set=1.02)
        n.add("Bus", "north::electricity", v_nom=20.0, x=11.0, y=49.2)
        n.add("Bus", "south::electricity", v_nom=20.0, x=12.0, y=48.0, v_mag_pu_set=1.0)
        n.add("Bus", "island::electricity", v_nom=20.0, x=12.5, y=48.0)
        # A slack takes up the balance; its set point of zero is what PyPSA adds the balance to.
        n.add("Generator", "grid", bus="grid::electricity", p_nom=100.0, control="Slack", p_set=0.0)
        n.add(
            "Generator", "pv", bus="south::electricity", p_nom=12.0, control="PV", p_set=10.0 * sun
        )
        n.add("Generator", "chp", bus="north::electricity", p_nom=8.0, p_set=5.0, q_set=1.5)
        n.add(
            "Generator", "diesel", bus="island::electricity", p_nom=6.0, control="Slack", p_set=0.0
        )
        n.add(
            "Load",
            "town",
            bus="north::electricity",
            p_set=12.0 + 4.0 * sun,
            q_set=0.3 * (12.0 + 4.0 * sun),
        )
        n.add("Load", "village", bus="south::electricity", p_set=6.0, q_set=1.0)
        n.add("Load", "hamlet", bus="island::electricity", p_set=2.5, q_set=0.5)
        n.add(
            "StorageUnit",
            "battery",
            bus="south::electricity",
            p_nom=3.0,
            max_hours=2.0,
            p_set=3.0 * np.sin(hours / 24 * 2 * np.pi),
        )
        n.add(
            "Transformer",
            "station_north",
            bus0="grid::electricity",
            bus1="north::electricity",
            s_nom=30.0,
            x=0.1,
            r=0.01,
        )
        n.add(
            "Transformer",
            "station_south",
            bus0="grid::electricity",
            bus1="south::electricity",
            s_nom=25.0,
            x=0.12,
            r=0.012,
        )
        n.add(
            "Line",
            "ring",
            bus0="north::electricity",
            bus1="south::electricity",
            s_nom=15.0,
            x=2.0,
            r=0.5,
            b=0.0001,
        )
        n.add(
            "Link",
            "cable",
            bus0="south::electricity",
            bus1="island::electricity",
            p_nom=5.0,
            p_set=1.5,
            efficiency=0.98,
        )
        n.add("ShuntImpedance", "compensation", bus="north::electricity", b=0.001)
        n.lpf()
        found = n.pf(use_seed=True, x_tol=1e-8)
        if not bool(found["converged"].all().all()):
            raise RuntimeError("the power flow did not converge")
    return n


# What the components of the network are called in the results document.
GENERATORS = {"north::pv": "north::pv", "wind@north": "north::wind", "gas": "south::gas"}
CARRIERS = {"north::pv": "electricity", "north::wind": "electricity", "south::gas": "electricity"}


def facts(n: Any) -> dict[str, Any]:
    """Say what PyPSA says about the optimised network, in the terms of the results document.

    Every number comes from the interface of PyPSA: the tables of the network
    and ``n.statistics``. None of it is read from a file.
    """
    energy = n.snapshot_weightings.generators
    costs = _costs(n)
    given = float((n.lines.capital_cost * n.lines.s_nom)[~n.lines.s_nom_extendable].sum())
    constant = float(getattr(n, "objective_constant", 0.0))
    found: dict[str, Any] = {
        "objective": sum(costs.values()),
        "objective_function_value": float(n.objective),
        "details": {"capital_cost_of_given_capacities": given},
        "timestamps": [stamp.isoformat() for stamp in n.snapshots],
        "capacities": {},
        "storage_capacities": {},
        "generation": {},
        "dispatch": {},
        "costs": {},
    }
    for name, key in GENERATORS.items():
        output = n.generators_t.p[name]
        found["capacities"][key] = float(n.generators.p_nom_opt[name])
        found["generation"][f"{key}::{CARRIERS[key]}"] = float((output * energy).sum())
        found["dispatch"][key.split("::")[1]] = [float(value) for value in output]
    discharge = n.storage_units_t.p["battery"].clip(lower=0)
    found["capacities"]["south::battery"] = float(n.storage_units.p_nom_opt["battery"])
    found["storage_capacities"]["south::battery"] = float(
        n.storage_units.p_nom_opt["battery"] * n.storage_units.max_hours["battery"]
    )
    found["generation"]["south::battery::electricity"] = float((discharge * energy).sum())
    found["dispatch"]["battery"] = [float(value) for value in discharge]
    withdrawal = n.stores_t.p["heat_store"].clip(lower=0)
    found["storage_capacities"]["south::heat_store"] = float(n.stores.e_nom_opt["heat_store"])
    found["generation"]["south::heat_store::heat"] = float((withdrawal * energy).sum())
    found["dispatch"]["heat_store"] = [float(value) for value in withdrawal]
    heat = (-n.links_t.p1["heat_pump"]).clip(lower=0)
    found["capacities"]["south::heat_pump"] = float(
        n.links.p_nom_opt["heat_pump"] * n.links.efficiency["heat_pump"]
    )
    found["generation"]["south::heat_pump::heat"] = float((heat * energy).sum())
    found["dispatch"]["heat_pump"] = [float(value) for value in heat]
    # A connection is listed at both of its ends.
    for end in ("north", "south"):
        found["capacities"][f"{end}::cable"] = float(n.links.p_nom_opt["cable"])
        found["capacities"][f"{end}::overhead"] = float(n.lines.s_nom_opt["overhead"])
    southward = (-n.links_t.p1["cable"]).clip(lower=0) + (-n.lines_t.p1["overhead"]).clip(lower=0)
    northward = (-n.links_t.p0["cable"]).clip(lower=0) + (-n.lines_t.p0["overhead"]).clip(lower=0)
    found["transmission_flow"] = {"north::south": [float(value) for value in southward - northward]}
    found["demand_timeseries"] = [float(value) for value in n.loads_t.p.sum(axis=1)]
    found["demand_by_location"] = {"south": float((n.loads_t.p.sum(axis=1) * energy).sum())}
    found["costs"] = costs
    if hasattr(n, "objective_constant"):
        found["details"]["objective_constant"] = constant
    stated = found["objective_function_value"] + constant
    if not math.isclose(stated, found["objective"] - given, rel_tol=1e-6):
        raise RuntimeError("the statistics of the network do not add up to its objective")
    return found


def power_flow_facts(n: Any) -> dict[str, Any]:
    """Say what PyPSA says about the solved power flow, in the terms of the results document.

    Every number comes from the tables of the network in memory, which hold
    a result for every bus and component, where the file holds only what
    differs from the defaults.
    """
    location = {bus: bus.split("::")[0] for bus in n.buses.index}
    found: dict[str, Any] = {
        "success": True,
        "termination_condition": "unknown",
        "objective": None,
        "timestamps": [stamp.isoformat() for stamp in n.snapshots],
        "capacities": {},
        "generation": {},
        "dispatch": {},
        "costs_by_location": {},
        "details": {"power_flow": {}},
    }
    for name, row in n.generators.iterrows():
        key = f"{location[row.bus]}::{name}"
        output = n.generators_t.p[name]
        found["capacities"][key] = float(row.p_nom)
        found["generation"][f"{key}::electricity"] = float(output.sum())
        found["dispatch"][name] = [float(value) for value in output]
    discharge = n.storage_units_t.p["battery"].clip(lower=0)
    found["capacities"]["south::battery"] = float(n.storage_units.p_nom["battery"])
    found["storage_capacities"] = {
        "south::battery": float(
            n.storage_units.p_nom["battery"] * n.storage_units.max_hours["battery"]
        )
    }
    found["generation"]["south::battery::electricity"] = float(discharge.sum())
    found["dispatch"]["battery"] = [float(value) for value in discharge]
    for table, size in ((n.lines, "s_nom"), (n.transformers, "s_nom"), (n.links, "p_nom")):
        for name, row in table.iterrows():
            for end in (row.bus0, row.bus1):
                found["capacities"][f"{location[end]}::{name}"] = float(row[size])
    found["demand_timeseries"] = [float(value) for value in n.loads_t.p.sum(axis=1)]
    arriving: dict[tuple[str, str], Any] = {}
    for table, series in (
        (n.lines, n.lines_t),
        (n.transformers, n.transformers_t),
        (n.links, n.links_t),
    ):
        for name, row in table.iterrows():
            origin, destination = location[row.bus0], location[row.bus1]
            arriving[origin, destination] = arriving.get((origin, destination), 0.0) + (
                -series.p1[name]
            ).clip(lower=0)
            arriving[destination, origin] = arriving.get((destination, origin), 0.0) + (
                -series.p0[name]
            ).clip(lower=0)
    flows: dict[str, Any] = {}
    for (origin, destination), series in arriving.items():
        first, second = sorted((origin, destination))
        signed = series if (origin, destination) == (first, second) else -series
        flows[f"{first}::{second}"] = flows.get(f"{first}::{second}", 0.0) + signed
    found["transmission_flow"] = {
        pair: [float(value) for value in series] for pair, series in flows.items()
    }
    details = found["details"]["power_flow"]
    details["slack_buses"] = [str(bus) for bus in n.sub_networks.slack_bus]
    details["voltage_magnitude"] = {
        bus: [float(value) for value in n.buses_t.v_mag_pu[bus]] for bus in n.buses.index
    }
    details["voltage_angle"] = {
        bus: [float(value) for value in n.buses_t.v_ang[bus]] for bus in n.buses.index
    }
    details["reactive_power"] = {
        **{
            f"{location[row.bus]}::{name}": [float(value) for value in n.generators_t.q[name]]
            for name, row in n.generators.iterrows()
        },
        "south::battery": [float(value) for value in n.storage_units_t.q["battery"]],
    }
    details["branch_loading"] = {}
    for table, series in ((n.lines, n.lines_t), (n.transformers, n.transformers_t)):
        for name, row in table.iterrows():
            apparent = [
                (series.p0[name] ** 2 + series.q0[name] ** 2) ** 0.5,
                (series.p1[name] ** 2 + series.q1[name] ** 2) ** 0.5,
            ]
            loading = apparent[0].where(apparent[0] >= apparent[1], apparent[1]) / row.s_nom
            details["branch_loading"][name] = [float(value) for value in loading]
    return found


def _costs(n: Any) -> dict[str, float]:
    """Return what each technology costs, as ``n.statistics`` has it.

    Versions of PyPSA before 0.26 have the statistics for groups of components
    alone. For them the costs are made from the tables of the network, as the
    statistics of the later versions make them.
    """
    names = {**{name: key.split("::")[1] for name, key in GENERATORS.items()}}
    costs: dict[str, float] = {}
    try:
        parts = [
            dict(statistic(groupby=False)) for statistic in (n.statistics.capex, n.statistics.opex)
        ]
    except (TypeError, UnboundLocalError):
        parts = [_costs_of_the_tables(n)]
    for part in parts:
        for (_, name), value in part.items():
            technology = names.get(name, name)
            costs[technology] = costs.get(technology, 0.0) + float(value)
    return costs


def _costs_of_the_tables(n: Any) -> dict[tuple[str, str], float]:
    """Return the capital and the operational cost of each component."""
    money = n.snapshot_weightings.objective
    costs: dict[tuple[str, str], float] = {}
    for kind, table, series, size, flow in (
        ("Generator", n.generators, n.generators_t, "p_nom_opt", "p"),
        ("StorageUnit", n.storage_units, n.storage_units_t, "p_nom_opt", "p"),
        ("Store", n.stores, n.stores_t, "e_nom_opt", "p"),
        ("Link", n.links, n.links_t, "p_nom_opt", "p0"),
        ("Line", n.lines, n.lines_t, "s_nom_opt", None),
    ):
        for name, row in table.iterrows():
            cost = float(row["capital_cost"] * row[size])
            if flow is not None:
                price = series["marginal_cost"].get(name, row["marginal_cost"])
                dispatch = series[flow][name]
                if kind == "StorageUnit":
                    dispatch = dispatch.clip(lower=0)
                cost += float((dispatch * price * money).sum())
            costs[kind, str(name)] = cost
    return costs


def build(directory: Path, *, formats: tuple[str, ...] = ("nc", "h5")) -> dict[str, Path]:
    """Write the network to ``directory`` in the formats asked for.

    Returns:
        The files that have been written, by a name for what they hold.
    """
    directory.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        solved = network()
        written["facts.json"] = directory / "facts.json"
        written["facts.json"].write_text(json.dumps(facts(solved), indent=1) + "\n")
        for extension in formats:
            target = directory / f"network.{extension}"
            target.unlink(missing_ok=True)
            if extension == "nc":
                solved.export_to_netcdf(target)
            else:
                solved.export_to_hdf5(target)
            written[f"network.{extension}"] = target
        target = directory / "unsolved.nc"
        target.unlink(missing_ok=True)
        network(solve=False).export_to_netcdf(target)
        written["unsolved.nc"] = target
        written.update(build_power_flow(directory))
        try:
            uncertain = stochastic()
        except (AttributeError, TypeError, KeyError):  # versions without scenarios
            return written
        target = directory / "stochastic.nc"
        target.unlink(missing_ok=True)
        uncertain.export_to_netcdf(target)
        written["stochastic.nc"] = target
    return written


def build_power_flow(directory: Path) -> dict[str, Path]:
    """Write the network of the power flow and its facts to ``directory``."""
    directory.mkdir(parents=True, exist_ok=True)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        flowed = power_flow()
        facts_path = directory / "power-flow.facts.json"
        facts_path.write_text(json.dumps(power_flow_facts(flowed), indent=1) + "\n")
        target = directory / "power-flow.nc"
        target.unlink(missing_ok=True)
        flowed.export_to_netcdf(target)
    return {"power-flow.nc": target, "power-flow.facts.json": facts_path}


if __name__ == "__main__":
    for name, path in build(Path(sys.argv[1])).items():
        sys.stdout.write(f"{name}: {path} ({path.stat().st_size} bytes)\n")
