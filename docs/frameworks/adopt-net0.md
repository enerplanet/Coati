# AdOpT-NET0

[AdOpT-NET0](https://adopt-net0.readthedocs.io/) writes the results of a run
into a folder of its own, as `optimization_results.h5`. The name of the
folder is made up from the time of the run, so a pipeline knows the folder
above but not the file. Coati accepts a directory that holds one such file:

```console
$ coati run/results results.json adopt-net0-v0-1-10
```

The file does not record the version of AdOpT-NET0 that wrote it. The
document states the version that the caller names.

## The file

The file is an HDF5 file of nested groups whose names are the names of the
model:

```text
summary/                                        one value for each figure of the run
topology/                                       nodes, periods and carriers
design/nodes/<period>/<node>/<technology>/      size and cost of a technology
design/networks/<period>/<network>/<arc>/       size and cost of an arc of a network
operation/technology_operation/<period>/<node>/<technology>/
operation/energy_balance/<period>/<node>/<carrier>/
operation/networks/<period>/<network>/<arc>/
k_means_specs/<period>/                         the typical days, if time is aggregated
```

It has neither dimensions nor attributes, and it records no times.

## Keys

| Key | From |
|---|---|
| `framework_version` | not recorded; the version that the caller names |
| `model_name` | `summary/case` |
| `solver` | not recorded: `null` |
| `termination_condition` | `summary/solver_status` |
| `objective` | `summary/total_npv`, else `summary/total_cost`; for a file of several periods the costs of the period that the document reports |
| `objective_function_value` | `summary/total_npv`, if the objective of the run was the cost |
| `timestamps` | the positions `0, 1, 2, ...`; instants with `--time-start` and `--time-step` |
| `capacities` | `size` of a technology, times its `rated_power` if it has one; `size` of an arc |
| `storage_capacities` | `size` of a technology that has a `storage_level` |
| `generation`, `dispatch` | the datasets `<carrier>_output` of a technology |
| `demand_timeseries`, `demand_by_location` | `demand` of the energy balances |
| `transmission_flow` | `flow` less `losses` of the arcs |
| `costs_by_location` | `capex_tot`, `opex_fixed_tot` and `opex_variable` of a technology; `capex`, `opex_fixed` and `opex_variable` of an arc; what is bought and sold at its price |
| `tech_metadata` | the kind follows from what a technology does; see below |
| `details.summary` | every figure of `summary` |
| `details.exported` | what each node sells, by `node::carrier` |

### The size of a technology

The size of a technology is in its own unit. For a technology that consists
of units of a rated power, such as a wind turbine, it is the number of
units, and the capacity is the size times the rated power. For a store it
is the energy that the store holds; it is reported as the storage capacity
and, since AdOpT-NET0 sizes a store by its energy, as the capacity as well,
unless the file has a `capacity_discharge`.

A technology that exists before the model decides anything has the name of
the technology with the ending `_existing`.

### The kind of a technology

AdOpT-NET0 does not name the kind of a technology. It follows from what the
technology does:

| The technology | Kind |
|---|---|
| has a `storage_level` | `storage` |
| takes in and puts out | `conversion` |
| takes in alone | `demand` |
| puts out alone | `supply` |

### Imports and exports

What a node buys and sells is no technology in AdOpT-NET0 but part of the
energy balance of the node. The document reports it like a technology,
because without it the supply of a model that buys its energy would be
empty:

| Technology | Kind | From |
|---|---|---|
| `import_<carrier>` | `supply` | `import`, at the price `import_price` |
| `generic_production_<carrier>` | `supply` | `generic_production`, which costs nothing |
| `export_<carrier>` | `demand` | `export`, at the price `export_price`; its cost is negative, a revenue |

A flow that stays below one millionth at every time is what a solver leaves
behind. It is not reported.

### Networks

An arc of a network has a direction. The group of an arc is named by its
two nodes written one after the other, which is ambiguous; Coati reads the
nodes from the datasets `fromNode` and `toNode`. The document names an arc
as Calliope 0.6 names the end of a link, by the network and the node that
the arc leads to:

```json
{
  "capacities": {
    "north::electricitySimple:south": 60.23,
    "south::electricitySimple:north": 60.23
  },
  "generation": {"south::electricitySimple:north::electricity": 1928.22}
}
```

A connection that works in both directions appears as two arcs of the same
size and cost, which AdOpT-NET0 charges once. In the document each of the
two arcs bears half of it.

The carrier of a network is not recorded. If the model has one carrier, it
is that one; else it is the carrier that the name of the network starts
with, as `electricity` in `electricitySimple`.

## The total cost

`objective` is the total cost that the summary states. The costs of the
document add up to it, unless the total holds costs that belong to no
technology: `carbon_cost`, `carbon_revenue` and `violation_cost`. The
document names them in a warning, and `details.summary` has their amounts.
If the costs do not add up to the total for another reason, a warning says
so.

## Typical days

AdOpT-NET0 can aggregate time into typical days. With the method 2, the
file has the time series of the whole modelled time, and there is nothing
to do. With the method 1, the model solves the typical days alone, and the
time series of the file cover the typical days; `k_means_specs` says which
typical day stands for which day.

The document gives the series of the whole modelled time in both cases.
Each time has the values of the typical day that stands for it, so that the
totals of the document are those of the model. The variable cost of a
technology, of which the file has the sum over the typical days, is scaled
with the flow of the technology to that end. `details.typical_days` is
`true`.

## Investment periods

A file holds one or several investment periods. The document reports one of
them, the first unless `--period` names another, and lists all under
`details.periods`. The `objective` is then the cost of that period, while
the figures of `details.summary` are those of all periods together.

!!! warning "AdOpT-NET0 0.1.10 writes the last period for every period"

    In a file of several periods that AdOpT-NET0 0.1.10 has written, the
    design of the nodes, the operation and the energy balances of every
    period are those of the *last* period. The function that writes the
    results takes them from the period that it has looked at last. The
    design of the networks and the summary are not affected.

    Coati cannot restore what the file does not hold. A document of a file
    whose periods hold the same results says so in a warning.

## What the file does not say

**The times.** The file records the number of times and not what they are.
Name the first time and the step, and the document has instants:

```console
$ coati run/results results.json adopt-net0-v0-1-10 \
      --time-start 2025-01-01T00:00 --time-step 1h
```

**The folder of the run.** `summary/time_stamp` holds the path of the folder
on the machine that ran the model. It says something about that machine and
nothing about the model, and is left out of the document.

**A model without a solution.** AdOpT-NET0 writes no file for a model that
has no solution.

## What Coati does not read

- The emissions of the technologies and of the networks; `details.summary`
  has their totals.
- The results of a Pareto front or of a Monte Carlo run as a whole.
  AdOpT-NET0 writes a folder for each of their points; each is a file that
  Coati reads.
