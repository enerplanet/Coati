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
`electricity`. Any other bus is its own location, and carries what its
attribute `carrier` says, or `AC` if it says nothing.

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
fails to meet if its carrier or its name is `load_shedding`, `load shedding`
or `unmet_demand`. It is reported as `unmet_demand_timeseries`, not as a
technology, and what it costs is no cost of the system.

## Keys

| Key | From |
|---|---|
| `framework_version` | the attribute `network_pypsa_version`; in HDF5 the column `pypsa_version` of the table `network` |
| `model_name` | the name of the network |
| `solver` | not recorded by PyPSA: `null` |
| `termination_condition` | `optimal` if the network has an objective, else `not_solved`; see below |
| `objective` | the sum of the costs of the document |
| `objective_function_value` | the objective of the network, `n.objective` |
| `timestamps` | the snapshots; instants as ISO 8601 text, anything else as the network names it |
| `weights` | the weighting `generators` of the snapshots, if the snapshots count differently |
| `periods` | the investment period of each snapshot, for a network with several |
| `scenarios` | the probability of each scenario, for a stochastic network |
| `capacities` | `p_nom_opt`, for a line or a transformer `s_nom_opt`; for a link of conversion times its `efficiency`, which is what it can put out |
| `storage_capacities` | `e_nom_opt` of a store; `p_nom_opt` times `max_hours` of a storage unit |
| `generation` | the output of each component over the snapshots, weighted with the weighting `generators` |
| `dispatch` | the output at each snapshot: `p` of a generator, what a storage unit or a store gives off, what arrives at the outputs of a link |
| `demand_timeseries`, `demand_by_location` | `p` of the loads; `p_set` for a network that has not been optimised |
| `transmission_flow` | what arrives at either end of the lines, transformers and links of transmission |
| `costs_by_location` | `capital_cost` times the capacity, and `marginal_cost` times the dispatch, weighted with the weighting `objective` |
| `tech_metadata` | the kind as above; `carrier_out` is the carrier of the bus that the component feeds |
| `coordinates` | `y` and `x` of the buses, if the network has the reference system 4326 |
| `details.objective_constant` | `n.objective_constant` |

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
`marginal_cost` times its dispatch.

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

Costs of other kinds than the capital and the marginal cost are not counted:
`marginal_cost_quadratic`, `marginal_cost_storage`, `spill_cost`,
`stand_by_cost`, `start_up_cost` and `shut_down_cost`. A document of a
network that states one of them names it in a warning.

## What the file does not say

**How the solver ended.** PyPSA does not record it. A network that has an
objective has been optimised, and PyPSA assigns a solution only if the
solver found the optimum; the termination condition of such a network is
reported as `optimal`.

**Which solver it was.** `solver` is `null`.

## A network that has not been optimised

A network without an objective has not been optimised. The document reports
the capacities that were given, `p_nom` in place of `p_nom_opt`, and the
demand that was set. It has no dispatch and no costs, `success` is `false`,
and a warning says that the capacities are not decided.

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

- The shadow prices of the buses and of the global constraints.
- Networks that were exported to CSV files.
