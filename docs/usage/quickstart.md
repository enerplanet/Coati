# Quickstart

## Convert the results of a model

Name the file of the model, the JSON file to write and the framework that
wrote the file:

```console
$ coati results.nc results.json calliope-v0-7-0
```

The framework is named with its version: `calliope-v0-7-0` is Calliope 0.7.0,
`pypsa-v1-2-4` is PyPSA 1.2.4 and `adopt-net0-v0-1-10` is AdOpT-NET0 0.1.10.
`coati frameworks` lists what is supported; [Frameworks](../frameworks/overview.md)
describes the identifiers in full.

The command is silent if all went well. `results.json` holds the
[results document](../documents/results.md):

```json
{
  "schema_version": "1.0",
  "framework": "calliope",
  "framework_version": "0.7.0",
  "model_name": "Coati test model",
  "solver": "cbc",
  "success": true,
  "termination_condition": "optimal",
  "objective": 15721.25665042096,
  "timestamps": ["2005-01-01T00:00:00", "2005-01-01T01:00:00", "..."],
  "capacities": {
    "north::pv": 136.3509,
    "south::battery": 100.0
  },
  "dispatch": {
    "pv": [0.0, 0.0, "..."]
  }
}
```

The example is shortened; a document holds every time and every technology.

## Let Coati find the framework

The framework can be left out. Coati then takes it from the file:

```console
$ coati results.nc results.json
```

Naming it is the better choice in a pipeline that knows what it has run. The
name is checked against the file, and a file that another framework has
written is refused:

```console
$ coati network.nc results.json calliope-v0-7-0
coati: network.nc: the file was written by PyPSA 1.2.4, not by Calliope 0.7.0
$ echo $?
1
```

Some files do not record the version that wrote them, those of AdOpT-NET0
and of Calliope 0.7.0 among them. The version that the caller names is then
the one that the document states.

## Look at a file first

`coati inspect` shows the format of a file, the framework that wrote it and
what the file holds, without reading the values:

```console
$ coati inspect network.nc
file:      network.nc
format:    netCDF-4
size:      223.5 kB
framework: PyPSA 1.2.4 (pypsa-v1-2-4)

group /
  attributes: network__objective, network_name, network_pypsa_version, ...
  dimensions: snapshots (24), carriers_i (3), generators_i (3), ...
  variables:
    snapshots             int64    (snapshots: 24)
    snapshots_snapshot    int64    (snapshots: 24)
    generators_i          string   (generators_i: 3)
    generators_p_nom_opt  float64  (generators_i: 3)
    ...
```

The output is shortened here.

## Write everything a file holds

`coati dump` writes the [dataset document](../documents/dataset.md): every
group, dimension, variable and attribute, with the values. It reads any
netCDF or HDF5 file, whatever wrote it:

```console
$ coati dump results.nc dataset.json
$ coati dump results.nc structure.json --no-data
$ coati dump results.nc flows.json --variable '/results/flow_*'
```

## Write to the standard output

`-` in place of the output writes the document to the standard output, for
the next program to read:

```console
$ coati results.nc - --compact | jq '.capacities'
```

## From Python

```python
import coati

document = coati.convert("results.nc", "results.json", "calliope-v0-7-0")
print(document["objective"])

results = coati.read_results("results.nc")
print(results.capacities["north::pv"])
```

See [Python package](python.md).
