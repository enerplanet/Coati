![Coati banner](assets/logos/coati-banner-dark.png#only-dark)
![Coati banner](assets/logos/coati-banner-light.png#only-light)

# Coati

Coati converts the result files of energy system models to JSON. It reads the
netCDF and HDF5 files that [Calliope](https://www.callio.pe/),
[PyPSA](https://pypsa.org/) and
[AdOpT-NET0](https://adopt-net0.readthedocs.io/) write, and writes what a
solved model says, in the same terms for every framework. It is a Python
package with a command line tool, and it needs none of the frameworks.

```console
$ pip install enerplanet-coati
$ coati results.nc results.json calliope-v0-7-0
```

## Two documents

Coati answers two questions about a file, each with a JSON document.

**What does the model say?** The [results document](documents/results.md)
holds the capacities, the generation, the dispatch, the demand, the exchange
between locations and the costs of a solved model. Its keys mean the same for
every framework, so that a program that reads it need not know which
framework solved the model. This is the document that `coati SOURCE OUTPUT
FRAMEWORK` writes.

```json
{
  "framework": "calliope",
  "framework_version": "0.7.0",
  "success": true,
  "termination_condition": "optimal",
  "objective": 15721.26,
  "timestamps": ["2005-01-01T00:00:00", "2005-01-01T01:00:00"],
  "capacities": {"north::pv": 136.35, "south::battery": 100.0},
  "generation": {"north::pv::power": 1382.45},
  "dispatch": {"pv": [0.0, 77.65]},
  "costs_by_tech": {"pv": 3.29, "gas": 15717.02},
  "tech_metadata": {"pv": {"parent": "supply", "carrier_out": "power"}}
}
```

**What is in the file?** The [dataset document](documents/dataset.md) holds
every group, dimension, variable and attribute of a file, with the values. It
needs no knowledge of a framework and reads any netCDF or HDF5 file. This is
the document that `coati dump SOURCE OUTPUT` writes.

## Where to go next

- [Installation](usage/installation.md) and the [Quickstart](usage/quickstart.md)
- Using the [command line](usage/cli.md) or the [Python package](usage/python.md)
- The frameworks: how a file is [recognised and named](frameworks/overview.md),
  and how each key follows from a file of [Calliope](frameworks/calliope.md),
  [PyPSA](frameworks/pypsa.md) and [AdOpT-NET0](frameworks/adopt-net0.md)
- The documents: [results](documents/results.md), [dataset](documents/dataset.md)
  and the [JSON](documents/json.md) they are written in
- For contributors: [architecture](development/architecture.md) and
  [testing](development/testing.md)

## Design goals

- **The same terms for every framework.** A key of the results document has
  one meaning. Where a framework has no such quantity the key is left out,
  and what holds for one framework alone is kept apart under `details`.
- **What the framework says.** A number of the document equals the number
  that the framework reports for its own model. The tests solve a model with
  each framework and compare the document, which Coati makes from the file
  alone, with what the framework says through its own interface.
- **A claim is checked.** The framework that a caller names is a claim about
  a file. A file of another framework or of another layout is refused: a
  mix-up in a pipeline is an error, not a document full of wrong numbers.
- **Strict JSON.** Result files are full of `NaN` and infinities, which are
  no JSON. Every number passes a policy before it is written, and what is
  written can be read by any parser.
- **Few dependencies.** h5py and NumPy. The frameworks, xarray, pandas and
  the netCDF library are not needed to read their files, so Coati installs
  where a framework does not, and next to any version of one.
- **Nothing is hidden.** What a reader of a document should know about its
  making, such as a file that holds several solutions of which the document
  reports one, is part of the document as a warning.
