# Results document

The results document says what a solved model says: what was built, what it
generated at each time, what was exchanged between locations and what it all
cost. Its keys mean the same whichever framework solved the model. The
pages of the frameworks tell how each key follows from a file of
[Calliope](../frameworks/calliope.md), [PyPSA](../frameworks/pypsa.md) and
[AdOpT-NET0](../frameworks/adopt-net0.md).

The document has the schema version `1.0`. Its
[JSON Schema](#the-schema) is part of the package.

## Names

A model consists of *technologies* at *locations* that take in and put out
*carriers*. The keys of the document join their names with `::`:

| Key | Names |
|---|---|
| `north::pv` | the technology `pv` at the location `north` |
| `north::pv::power` | the carrier `power` of the technology `pv` at the location `north` |
| `north::south` | the two locations `north` and `south`, in the order of their names |

A technology of transmission may name the location at the other end of its
link, after a colon: `north::line:south` is the end at `north` of a line to
`south`. Calliope 0.6 and AdOpT-NET0 name their connections this way.

## Units

The document has no units: Calliope, PyPSA and AdOpT-NET0 compute with the
numbers that a model gives them and know no units themselves. A capacity is
in the unit of power of the model, generation in its unit of energy, and a
cost in its currency.

## Keys

The keys marked *always* are part of every document. The others are left
out where a model has nothing to say: a model without storage has no
`storage_capacities`.

### The run

| Key | Type | | Meaning |
|---|---|---|---|
| `schema_version` | text | always | the version of the layout of the document, `1.0` |
| `framework` | text | always | `calliope`, `pypsa` or `adopt-net0` |
| `framework_version` | text or null | always | the version of the framework, as the file states it or as the caller named it; null if neither is known |
| `model_name` | text or null | always | the name of the model |
| `solver` | text or null | always | the solver, if the file records it |
| `success` | true or false | always | whether the model has a solution |
| `termination_condition` | text | always | how the solver ended, in the words of the framework, or `not_solved` or `unknown` |
| `objective` | number or null | always | the cost of the system; null if the model has no solution |
| `objective_function_value` | number | | the value of the objective function, which may include penalties and weights that are no cost |

`objective` is the sum of the costs that the document lists under
`costs_by_location`. Where it is not, because the file states costs that
belong to no technology, a warning says so.

### Time

| Key | Type | | Meaning |
|---|---|---|---|
| `timestamps` | list | always | the times of the time series: ISO 8601 text, or the positions if the file records no times |
| `weights` | list of numbers | | how much each time counts towards a total; present if the times count differently |
| `periods` | list | | the investment period of each time, for a model with several |
| `scenarios` | object | | the probability of each scenario of a stochastic model, whose expectation the document reports |

Every time series of the document has one number for each of the
`timestamps`, in their order. A time is written without a zone, as the
frameworks keep it: `2025-01-01T00:00:00`.

A model may count a time more than once: a time step of three hours, or a
day that stands for ten. The *time series* of the document are those of the
model, one value for each time. The *totals*, such as `generation` or
`demand_by_location`, count each time with its weight.

### Capacities and generation

| Key | Type | | Meaning |
|---|---|---|---|
| `capacities` | object | always | the capacity of each technology at each location, by `location::technology` |
| `storage_capacities` | object | | the capacity of each store to hold energy, by `location::technology` |
| `generation` | object | always | what each technology puts out over the modelled time, by `location::technology::carrier` |
| `dispatch` | object of lists | always | what each technology puts out at each time, all locations and carriers together, by technology |

`dispatch` leaves out the technologies of demand and of transmission, and
the technologies that put out nothing.

### Demand

| Key | Type | | Meaning |
|---|---|---|---|
| `demand_timeseries` | list of numbers | always | the demand at each time, all locations together; empty if the model has no demand |
| `demand_by_location` | object | | the demand over the modelled time at each location |
| `unmet_demand_timeseries` | list of numbers | | the demand that is not met at each time |
| `unmet_demand_by_location` | object | | the demand that is not met over the modelled time, at each location |
| `total_unmet_demand` | number | | the demand that is not met, all times and locations together |

Demand is a magnitude: it is positive, although a framework may keep what a
technology takes in as a negative number. The keys of demand that is not met
are present only if some demand is not met.

### Exchange between locations

| Key | Type | | Meaning |
|---|---|---|---|
| `transmission_flow` | object | always | the exchange between each pair of locations, by `a::b` |
| `imports_by_location` | object | | what each location takes in through transmission over the modelled time |
| `exports_by_location` | object | | what each location gives away through transmission over the modelled time |

```json
{
  "transmission_flow": {
    "north::south": {
      "from": "north",
      "to": "south",
      "timeseries": [133.62, 76.09, 0.0, -12.5]
    }
  }
}
```

The two locations of a pair are in the order of their names. `timeseries` is
the net flow that arrives at `to` from `from`; it is negative if more flows
the other way. All technologies that join the two locations are counted
together, and what is counted is what arrives, after the losses. A pair that
exchanges nothing is left out.

### Costs

| Key | Type | | Meaning |
|---|---|---|---|
| `costs_by_location` | object of objects | always | the cost of each technology at each location, by location and technology |
| `costs_by_tech` | object | always | the cost of each technology, all locations together |

`costs_by_location` has every entry, those of no cost and the negative ones,
which are revenues, among them. `costs_by_tech` lists the technologies
whose cost is greater than zero.

A connection between two locations has its capacity at both, and each bears
half of its cost.

### Technologies

| Key | Type | | Meaning |
|---|---|---|---|
| `tech_metadata` | object of objects | always | the kind of each technology and what it puts out |
| `tech_parents` | object | always | the kind of each technology; the same as `parent` in `tech_metadata` |
| `coordinates` | object of pairs | | the latitude and the longitude of each location, in this order |

```json
{
  "tech_metadata": {
    "pv": {
      "parent": "supply",
      "carrier_out": "power",
      "display_name": "Solar photovoltaics",
      "color": "#F9D956"
    }
  }
}
```

`parent` is the kind of the technology: `supply`, `demand`, `storage`,
`conversion` or `transmission`, or a kind of the framework such as
`supply_plus` or `conversion_plus` of Calliope 0.6. `carrier_out` is the
carrier that the technology puts out, the primary one if it has several, and
empty if it puts out none. `display_name` and `color` are present if the
file has them; `--no-labels` leaves them out.

### The document itself

| Key | Type | | Meaning |
|---|---|---|---|
| `details` | object | | what else the file says, in the terms of the framework |
| `warnings` | list of texts | always | what a reader of the document should know about its making |
| `metadata` | object | always | how the document was made |

`details` holds what has a meaning for one framework alone; its keys are
described on the pages of the frameworks.

`warnings` is empty for most files. A warning says that the document is not
all that the file holds, or that the file is not what it seems:

- the file holds several solutions of the SPORES mode, or several investment
  periods, of which the document reports one
- the numbers are the expectation over the scenarios of a stochastic network
- the network has not been optimised
- the file states a version that was not named, or one that Coati does not
  know
- the costs do not add up to the objective
- a link of the file leads into another file, which is not read

```json
{
  "metadata": {
    "generator": "coati",
    "generator_version": "0.1.0a0",
    "framework_id": "calliope-v0-7-0",
    "framework_family": "calliope-v0-7",
    "source": {"name": "results.nc", "format": "netcdf4", "size": 460016}
  }
}
```

`source` names the file without its directory, which says something about
the machine and nothing about the model.

## What adds up

The numbers of a document are related, and a program may rely on it:

| This | is |
|---|---|
| `objective` | the sum of all costs of `costs_by_location` |
| an entry of `costs_by_tech` | the sum of the costs of the technology at all locations |
| the `generation` of a technology, all locations and carriers together | the sum of its `dispatch`, each time counted with its weight |
| an entry of `demand_by_location`, all locations together | the sum of `demand_timeseries`, each time counted with its weight |
| the sum of `imports_by_location` | the sum of `exports_by_location` |
| `tech_parents` | `parent` of `tech_metadata`, for every technology |

Every technology that a key of the document names has an entry in
`tech_metadata`.

## Numbers that are not finite

A number of the document may be null: a file holds `NaN` where a quantity
has no value, and JSON has no such number. See [JSON](json.md).

## The schema

```console
$ coati schema results
```

prints the JSON Schema of the document, a schema of the draft 2020-12. The
schema is strict: it knows every key of the document and refuses any other
at the top, so that a key that is misspelt does not go unnoticed. `details`
may hold anything.

```python
import json
from importlib import resources

import jsonschema

schema = json.loads(
    resources.files("coati.schemas").joinpath("results.schema.json").read_text("utf-8")
)
with open("results.json", encoding="utf-8") as file:
    jsonschema.validate(json.load(file), schema)
```

## Changes of the layout

`schema_version` has two parts. A document of a later version with the same
first part has keys that an earlier one lacks, and nothing that a reader of
the earlier version relies on has changed. A change of the meaning or of
the type of a key, or a key that is removed, raises the first part.

## TEMPO

The document holds the keys that [TEMPO](https://github.com/THD-Spatial-AI/TEMPO)
reads from the results of a model: `model_name`, `solver`, `success`,
`termination_condition`, `objective`, `capacities`, `generation`,
`dispatch`, `timestamps`, `transmission_flow`, `demand_timeseries`,
`costs_by_tech`, `costs_by_location`, `tech_metadata` and `tech_parents`.
