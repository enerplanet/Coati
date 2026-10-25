# Calliope

[Calliope](https://www.callio.pe/) writes a model with its results as a
netCDF-4 file: `model.to_netcdf("results.nc")`. The versions 0.6 and 0.7 lay
out their files in ways that have nothing in common, so Coati has an
extractor for each. Both report locations as Calliope names them, *locations*
in 0.6 and *nodes* in 0.7.

## Calliope 0.7

The file has three groups. `inputs` holds the parameters of the model,
`results` the solution, and the attributes of `attrs` the configuration and
the record of the run as YAML. The arrays have the dimensions `nodes`,
`techs`, `carriers`, `costs` and `timesteps`. An element that does not
exist, such as a technology at a node where it is not installed, is `NaN`
and is left out of the document.

| Key | From |
|---|---|
| `framework_version` | `calliope_version_initialised` of `attrs.runtime`, else `init.calliope_version` of `attrs.config`. Calliope 0.7.0 records the version only if the model declares one. |
| `model_name` | `init.name` of `attrs.config` |
| `solver` | `solve.solver` of `attrs.config` |
| `termination_condition` | `termination_condition` of `attrs.runtime`; `unknown` if the record lacks it, `not_solved` if the file holds no results |
| `success` | the file holds results and the termination condition is that of a solution, such as `optimal` |
| `objective` | the sum of `results/cost`, each class of cost counted with its weight `inputs/objective_cost_weights`; a class without a weight counts in full |
| `objective_function_value` | the variable of the results that is named like the objective, `min_cost_optimisation` unless `build.objective` of the configuration says otherwise. It includes the penalty for demand that is not met. |
| `timestamps` | `results/timesteps` |
| `weights` | `inputs/timestep_weights`, if the times count differently |
| `capacities` | `results/flow_cap`, the largest over the carriers, by `node::tech` |
| `storage_capacities` | `results/storage_cap` by `node::tech` |
| `storage_levels` | `results/storage` by `node::tech` |
| `generation` | `results/flow_out`, each time counted with its weight, by `node::tech::carrier` |
| `dispatch` | `results/flow_out`, all nodes and carriers together, by `tech`; without the technologies of demand and of transmission |
| `demand_timeseries`, `demand_by_location` | `results/flow_in` of the technologies whose `inputs/base_tech` is `demand` |
| `unmet_demand_*` | `results/unmet_demand`, which exists if the model was built with `ensure_feasibility` |
| `transmission_flow` | `results/flow_out` of the technologies whose `base_tech` is `transmission`: what arrives at each of the two nodes that the technology joins |
| `prices` | `results/shadow_price_system_balance` by `node::carrier`, which the file holds if `solve.shadow_prices` of the configuration lists `system_balance` |
| `costs_by_location` | `results/cost`, weighted as for the objective, by node and `tech` |
| `fixed_costs_by_location` | `results/cost_investment_annualised` and `results/cost_operation_fixed`, weighted as for the objective |
| `variable_costs_by_location` | the rest of the cost, which is `results/cost_operation_variable` over the times |
| `emissions_by_location` | the class `emissions` of `results/cost`, if the model has one, as Calliope's models name it by convention |
| `tech_metadata` | `parent` is `inputs/base_tech`; `carrier_out` the first carrier that `inputs/carrier_out` marks; `display_name` and `color` are `inputs/name` and `inputs/color` |
| `coordinates` | `inputs/latitude` and `inputs/longitude` |
| `details.mode` | `init.mode` of `attrs.config`: `base`, `operate` or `spores` |
| `details.costs_by_class` | `results/cost` of each class, by `node::tech`, as the file has it, unweighted |
| `details.systemwide_capacity_factor`, `details.systemwide_levelised_cost`, `details.total_levelised_cost`, `details.total_generation` | the figures of the same names that Calliope computes from the solution, by `tech::carrier`, `tech::carrier::class`, `carrier::class` and `tech::carrier` |
| `details.source_use`, `details.unused_supply` | the series of the same names, by `node::tech` and `node::carrier` |

The two parts of the cost are present where the file has any of the three
variables that Calliope writes for them; the operate mode writes none, and
its document has the costs alone.

### Transmission

A technology of transmission joins two nodes, which `inputs/link_from` and
`inputs/link_to` name; a preview of 0.7 that does not write them is read by
the two nodes at which the technology is defined. The capacity of the
technology is listed at both nodes, and each bears half of its cost, as
Calliope itself reports it.

### SPORES

In the SPORES mode the results have a further dimension `spores`. The first
of the solutions is the optimum; the others are alternatives that cost no
more than the slack allows. The document reports the first and lists the
cost, the capacities and the generation of every solution under
`details.spores`:

```json
{
  "details": {
    "mode": "spores",
    "spores": [
      {"spore": "0", "cost": 15721.26, "capacities": {"north::pv": 136.35}, "generation": {}},
      {"spore": "1", "cost": 18865.51, "capacities": {"north::pv": 128.27}, "generation": {}}
    ]
  }
}
```

The figures of each are made as the document makes them for the first, so
that the first entry says what the document says. A warning points out that
the file holds several solutions.

### Operate mode

In the operate mode the capacities are given, not decided. The file has
them as parameters in `inputs`, and the results have none; the document
takes them from there. A parameter that holds for every node at which a
technology is defined is stored without the dimension of the nodes; the
document lists it at each of these nodes.

## Calliope 0.6

The file has one group. Its variables are defined over sets whose labels
join a location, a technology and a carrier: `region1::ccgt` in the set
`loc_techs`, `region1::ccgt::power` in `loc_tech_carriers_prod`. The keys of
the document are these labels.

| Key | From |
|---|---|
| `framework_version` | the attribute `calliope_version` |
| `model_name` | `name` of the attribute `model_config` |
| `solver` | `solver` of the attribute `run_config` |
| `termination_condition` | the attribute `termination_condition` |
| `objective` | the sum of `cost`, each class of cost counted with its weight, `objective_options.cost_class` of `run_config`; a class that the list does not name does not count |
| `objective_function_value` | the attribute `objective_function_value` |
| `timestamps`, `weights` | `timesteps` and `timestep_weights` |
| `capacities` | `energy_cap` by the labels of `loc_techs` |
| `storage_capacities` | `storage_cap` |
| `storage_levels` | `storage`, by the labels of `loc_techs_store` |
| `generation` | `carrier_prod`, each time counted with its weight |
| `dispatch` | `carrier_prod` by technology, without demand and transmission |
| `demand_timeseries`, `demand_by_location` | `carrier_con` of the technologies that inherit from `demand` |
| `unmet_demand_*` | `unmet_demand` |
| `transmission_flow` | `carrier_prod` of the technologies of transmission |
| `costs_by_location` | `cost`, weighted as for the objective |
| `fixed_costs_by_location` | `cost_investment`, weighted as for the objective, which Calliope 0.6 annualises together with the fixed costs of operation |
| `variable_costs_by_location` | the rest of the cost, which is `cost_var` over the times |
| `emissions_by_location` | the class `emissions` of `cost`, if the model has one |
| `tech_metadata` | `parent` is the abstract technology that `inheritance` ends with; `carrier_out` the primary carrier of `lookup_primary_loc_tech_carriers_out`, else the first carrier that the technology produces; `display_name` and `color` are `names` and `colors` |
| `coordinates` | `loc_coordinates`, if it holds `lat` and `lon`; locations in a plane, with `x` and `y`, are left out |
| `details.mode` | `mode` of `run_config` |
| `details.costs_by_class` | `cost` of each class, by the labels of `loc_techs_cost`, unweighted |
| `details.systemwide_capacity_factor`, `details.systemwide_levelised_cost`, `details.total_levelised_cost` | the figures of the same names, by `tech::carrier`, `tech::carrier::class` and `carrier::class` |
| `details.resource_con` | the series of the same name, by the labels of its set |

### Transmission

Calliope 0.6 names a technology of transmission by the technology and the
location at the other end of the link: `region1::ac_transmission:region2` is
the end at `region1` of a link to `region2`, and what it produces is what
arrives at `region1` from `region2`. The document keeps these names:

```json
{
  "capacities": {"north::line:south": 136.35, "south::line:north": 136.35},
  "generation": {"south::line:north::power": 1354.8},
  "tech_metadata": {
    "line": {"parent": "transmission", "carrier_out": ""},
    "line:north": {"parent": "transmission", "carrier_out": "power"}
  }
}
```

Each end has an entry of its own in `tech_metadata`, with the kind and the
labels of the technology.

### SPORES

As for Calliope 0.7: the results have the dimension `spores`, the document
reports the first solution and lists all under `details.spores`.

## What Coati does not read

- The shadow prices of constraints other than the system balance, which
  Calliope 0.7 can save as well.
- The capacity factor of each technology at each time, `capacity_factor`,
  which is the dispatch over the capacity.
- The inputs of a model beyond those that the results document needs. The
  [dataset document](../documents/dataset.md) holds them all: `coati dump`.
