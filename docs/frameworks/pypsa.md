# PyPSA

[PyPSA](https://pypsa.org/) exports a network with its results to a file of
either format:

```python
n.optimize()
n.export_to_netcdf("network.nc")
n.export_to_hdf5("network.h5")
```

Coati reads both and makes the same document from both. The files hold the
tables of the network: for every kind of component a table of attributes
with one row for each component, and a table of time series for each
attribute that varies with time.

## From a network to locations and technologies

A PyPSA network consists of components that are attached to buses. The
results document speaks of technologies at locations, so the components are
translated:

**Location.** The location of a component is that of its bus. A bus that is
named `north::electricity` is at the location `north` and carries
`electricity`, whatever its attribute `carrier` says; a further part of the
name, as in `north::electricity::battery`, tells the buses of one location
and one carrier apart. Any other bus is its own location, and carries what
its attribute `carrier` says, or `AC` if it says nothing.

**Technology.** The technology is the name of the component, without the
location if the name states it as `north::pv` or as `pv@north`. Components
of the same name at several locations are one technology.

**Kind.** The kind follows from the kind of the component:

| Component | Kind |
|---|---|
| `Generator` | `supply` |
| `Load` | `demand` |
| `StorageUnit`, `Store` | `storage` |
| `Link` | `transmission` if it joins two locations on one carrier and has no further outputs, else `conversion` |
| `Line`, `Transformer` | `transmission` |

**Demand that is not met.** A generator stands for demand that the system
fails to meet if its carrier or its name is `unmet`, `unmet_demand`,
`load_shedding` or `load shedding`. It is reported as
`unmet_demand_timeseries`, not as a technology, and what it costs is no cost
of the system.

## Keys

| Key | From |
|---|---|
| `framework_version` | the attribute `network_pypsa_version`; in HDF5 the column `pypsa_version` of the table `network` |
| `model_name` | the name of the network |
| `solver` | not recorded by PyPSA: `null` |
| `termination_condition` | `optimal` if the network has an objective; `converged`, `not_converged` or `unknown` for a [power flow](#power-flow); else `not_solved`; see below |
| `objective` | the sum of the costs of the document; null for a power flow |
| `objective_function_value` | the objective of the network, `n.objective` |
| `timestamps` | the snapshots; instants as ISO 8601 text, anything else as the network names it |
| `weights` | the weighting `generators` of the snapshots, if the snapshots count differently |
| `periods` | the investment period of each snapshot, for a network with several |
| `scenarios` | the probability of each scenario, for a stochastic network |
| `capacities` | `p_nom_opt`, for a line or a transformer `s_nom_opt`; for a link of conversion times its `efficiency`, which is what it can put out |
| `storage_capacities` | `e_nom_opt` of a store; `p_nom_opt` times `max_hours` of a storage unit |
| `storage_levels` | `state_of_charge` of a storage unit, `e` of a store, for a network that was optimised; zero where PyPSA writes none |
| `generation` | the output of each component over the snapshots, weighted with the weighting `generators` |
| `dispatch` | the output at each snapshot: `p` of a generator, what a storage unit or a store gives off, what arrives at the outputs of a link |
| `curtailment` | for a generator whose `p_max_pu` varies with time: `p_max_pu` times `p_nom_opt` less `p`, where that is positive, weighted with the weighting `generators`; see below |
| `demand_timeseries`, `demand_by_location` | `p` of the loads; `p_set` for a network that has not been optimised |
| `transmission_flow` | what arrives at either end of the lines, transformers and links of transmission |
| `prices` | `marginal_price` of the buses; see below |
| `costs_by_location` | `capital_cost` times the capacity, `marginal_cost` times the dispatch, weighted with the weighting `objective`, and the other costs of operation that the network states |
| `fixed_costs_by_location` | `capital_cost` times the capacity, the annualised investment and the fixed costs of operation together, as PyPSA keeps them |
| `variable_costs_by_location` | the costs of operation: `marginal_cost` times the dispatch and the other costs of operation |
| `emissions_by_location` | what each generator burns, times what its carrier emits per unit; see below |
| `tech_metadata` | the kind as above; `carrier_out` is the carrier of the bus that the component feeds |
| `coordinates` | `y` and `x` of the buses, if the network has the reference system 4326 |
| `details.objective_constant` | `n.objective_constant` |
| `details.global_constraints` | the global constraints of the network, such as a limit on emissions; see below |
| `details.power_flow` | what a [power flow](#power-flow) found |

### Defaults

PyPSA writes only the attributes that differ from their defaults. An
attribute that the file lacks has the default that PyPSA gives it: a
`marginal_cost` of zero, an `efficiency` of one, `max_hours` of one, a
capacity that is not extendable.

### Connections

A line, a transformer or a link of transmission joins two locations. Its
capacity is listed at both, and each bears half of its cost, as Calliope
reports the transmission of its models. The technology has the same name at
both ends. A component that joins two buses of one location is listed there
once.

## Costs and the objective

The costs follow the definitions of `n.statistics`: the capital cost of a
component is its `capital_cost` times its optimised capacity, whether or not
the capacity was extendable, and its operational cost is its
`marginal_cost` times its dispatch, together with every other cost of
operation that PyPSA knows and the network states:

| Cost | Applies to | Counted as |
|---|---|---|
| `marginal_cost_quadratic` | the dispatch, squared | weighted with the weighting `objective` |
| `marginal_cost_storage` | the energy held: `state_of_charge` of a storage unit, `e` of a store | weighted |
| `spill_cost` | `spill` of a storage unit | weighted |
| `stand_by_cost` | `status` of a committable generator or link, the hours it is on | weighted |
| `start_up_cost`, `shut_down_cost` | `start_up` and `shut_down` of a committable unit | once per event |

Each is counted from the time series that PyPSA writes for it. PyPSA writes
a series only where a value differs from the default, so a series that the
file lacks has the default: a unit that never started up, a store that
never spilled, and a committable unit that was never off, whose `status`
defaults to on and which stands by at every snapshot.

The `objective` of the document is the sum of these costs, so that the costs
of the technologies add up to it, as they do for the other frameworks. The
objective of the network, `n.objective`, is another number, which the
document reports as `objective_function_value`. PyPSA leaves out of it the
capital cost of the capacities that were given, and counts in it what the
generators cost that stand for demand that is not met. `details` names these
parts, so that the two can be reconciled:

```text
objective_function_value + objective_constant
    = objective - capital_cost_of_given_capacities + cost_of_unmet_demand
```

```json
{
  "objective": 7434.38,
  "objective_function_value": 7384.38,
  "details": {
    "objective_constant": 0.0,
    "capital_cost_of_given_capacities": 50.0
  }
}
```

Coati checks this equation. If it does not hold, the objective of the
network is not the cost of what the network holds, and the document says so
in a warning. Two cases are common. A network may have been optimised with
an objective of its own, as when alternatives to the optimum are looked for:
its objective is then no cost at all. And a network may have been optimised
in several steps, as with a rolling horizon: its objective is that of the
last step, while its dispatch is that of all. In both cases the `objective`
of the document is what the system costs, and
`objective_function_value` what PyPSA has recorded.

The check is left out for a network with several investment periods, whose
objective weighs the periods.


## Prices

PyPSA records the marginal price of every bus at every snapshot, the dual
of the balance of the bus, in `buses_t.marginal_price`. The document
reports it under `prices`, by the location and the carrier of the bus. A
bus named `north::electricity` is the price of `electricity` at `north`; a
bus named with more parts, such as `north::electricity::battery`, keeps its
name, which tells it from the bus of the location and the carrier; any
other bus is named by its location and its carrier. PyPSA writes the series
where a price is not zero; a bus whose price stays zero has none, and the
document reports zero.

## Emissions

PyPSA records no emissions. It records what each carrier emits per unit, the
attribute `co2_emissions` of the carriers, and counts the emissions of the
network towards a global constraint of the type `primary_energy` by what is
burnt. The document counts them the same way:

- A generator emits its output over its `efficiency`, times what its
  carrier emits per unit. Every generator is listed once any carrier of the
  network emits, with nothing for a carrier that does not; a generator that
  stands for demand that is not met is left out.
- A storage unit or a store whose carrier emits and that is not cyclic emits
  what it gives off over the snapshots: the energy it held at the start,
  `state_of_charge_initial` or `e_initial`, less what it holds at the end.
  What it keeps is negative.

`total_emissions` adds them up, with the weighting `generators`. The
weighting of investment periods is not applied.

The global constraints of the network, such as a cap on emissions, are
reported under `details.global_constraints` as PyPSA states them, with
the defaults PyPSA gives an attribute it does not write:

```json
{
  "details": {
    "global_constraints": {
      "co2_cap": {
        "type": "primary_energy",
        "carrier_attribute": "co2_emissions",
        "sense": "<=",
        "constant": 1000000.0,
        "mu": 0.0
      }
    }
  }
}
```

`constant` is the limit, `mu` its shadow price: what one more unit of the
limit would save.

## Curtailment

A generator whose `p_max_pu` varies with time has a resource that the file
records, the sun or the wind. What such a generator could have put out,
`p_max_pu` times `p_nom_opt`, less what it did put out, where that is
positive, is its curtailment, added up over the snapshots with the weighting
`generators`. A generator whose availability does not vary has no resource to
curtail, and is not listed; `n.statistics.curtailment` of PyPSA 1.2 counts
the spare capacity of every generator instead, and so says more.

## What the file does not say

**How the solver ended.** PyPSA does not record it. A network that has an
objective has been optimised, and PyPSA assigns a solution only if the
solver found the optimum; the termination condition of such a network is
reported as `optimal`.

**Which solver it was.** `solver` is `null`.

## A network that has not been optimised

A network without an objective has not been optimised. If its buses have no
results either, the document reports the capacities that were given, `p_nom`
in place of `p_nom_opt`, and the demand that was set. It has no dispatch and
no costs, `success` is `false`, and a warning says that the capacities are
not decided.

## Power flow

`n.lpf()` and `n.pf()` solve the electrical network for a dispatch that is
given, and optimise nothing: they find the voltage of every bus, the flow
on every line and transformer and the power that the slack takes up. They
leave no objective behind, and the buses have results: `p`, `v_ang` and,
for a non-linear power flow, `v_mag_pu` and `q`. Such a network holds the
solution of a power flow, and its document says so:

- `capacities` are those given, as for a network that has not been
  optimised; `dispatch`, `generation`, `demand_timeseries` and
  `transmission_flow` are as solved, the slack carrying the losses.
- `objective` is null and there are no costs.
- `details.power_flow` holds what the power flow found:

| Key | Meaning |
|---|---|
| `slack_buses` | the slack bus of each sub-network, from the table `sub_networks` |
| `voltage_magnitude` | the voltage of each bus of alternating current at each snapshot, in per unit, by the name of the bus |
| `voltage_angle` | its angle, in radians |
| `reactive_power` | the reactive power that each generator and storage unit supplies at each snapshot, by `location::technology`; present if the network was solved for it, with a non-linear power flow |
| `branch_loading` | the loading of each line and transformer at each snapshot, by its name: the apparent power at the fuller of its ends over its rating `s_nom`; null where the rating is zero |
| `converged` | whether the power flow converged at each snapshot, if a record says; see below |
| `iterations` | the iterations each snapshot took, if the record says |

PyPSA writes a result only where it differs from its default. A bus whose
voltage stays at 1 per unit, such as a slack bus or every bus of a linear
power flow, has no series of it in the file, nor has a bus whose angle is
zero or a unit whose reactive power is; the document fills in the defaults.

**Convergence.** PyPSA does not record whether a power flow converged.
[MEME](../usage/meme.md), which runs power flows through PyPSA, writes it
down next to the network, in `power_flow/convergence.csv`: one row for each
snapshot with a column `converged` and, for the Newton-Raphson method, a
column `iterations`. If that file lies next to the network, the document
takes the convergence from it: `success` is whether every snapshot
converged, `termination_condition` is `converged` or `not_converged`, and
`details.power_flow` lists `converged` and `iterations`. Without a record,
`termination_condition` is `unknown`, `success` is `true`, since the file
holds a solution, and the warning says that the convergence is not recorded.
A record that does not fit the network, with another number of rows or
without the column, is not used, and the warning says why.

```json
{
  "success": true,
  "termination_condition": "converged",
  "objective": null,
  "details": {
    "power_flow": {
      "converged": [true, true, true, true],
      "iterations": [3, 3, 2, 2],
      "slack_buses": ["hv::electricity"],
      "voltage_magnitude": {"hv::electricity": [1.0, 1.0, 1.0, 1.0], "mv1::electricity": [0.98, 0.98, 0.97, 0.99]},
      "voltage_angle": {"hv::electricity": [0.0, 0.0, 0.0, 0.0], "mv1::electricity": [-0.09, -0.09, -0.09, -0.07]},
      "reactive_power": {"hv::grid": [2.26, 3.05, 4.19, 4.09], "mv2::pv": [4.24, 4.35, 3.72, 1.48]},
      "branch_loading": {"l12": [0.47, 0.42, 0.26, 0.06], "trafo": [0.49, 0.51, 0.49, 0.32]}
    }
  }
}
```

## Stochastic networks

A stochastic network holds one set of results for each scenario. The
document reports their expectation, the sum weighted with the probabilities
of the scenarios, which is also what the objective of the network is.
`scenarios` lists the probabilities, and a warning points out that the
numbers are expectations.

## HDF5

`export_to_hdf5` writes the tables with pandas, in the format of PyTables.
Coati reads that format itself and needs neither. pandas stores the names of
the columns as pickles, the serialisation format of Python, which can run
code when it is read. Coati reads them with an unpickler that refuses every
class and function: a pickle can yield lists, texts and numbers and nothing
else, and a file that holds more is refused.

## What Coati does not read

- The shadow prices of the constraints of the components, `mu_upper` and
  `mu_lower`.
- The inputs of a power flow: the set points, the controls and the shunt
  impedances.
- Networks that were exported to CSV files.
