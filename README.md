![Coati banner](docs/assets/logos/coati-banner-dark.png#gh-dark-mode-only)
![Coati banner](docs/assets/logos/coati-banner-light.png#gh-light-mode-only)

# Coati

[![CI](https://github.com/enerplanet/Coati/actions/workflows/ci.yml/badge.svg)](https://github.com/enerplanet/Coati/actions/workflows/ci.yml)
[![MkDocs](https://github.com/enerplanet/Coati/actions/workflows/docs.yml/badge.svg)](https://enerplanet.github.io/Coati)
[![PyPI](https://img.shields.io/pypi/v/enerplanet-coati)](https://pypi.org/project/enerplanet-coati/)
[![Python](https://img.shields.io/pypi/pyversions/enerplanet-coati)](https://pypi.org/project/enerplanet-coati/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Coati converts the result files of energy system models to JSON. It reads the
netCDF and HDF5 files that [Calliope](https://www.callio.pe/),
[PyPSA](https://pypsa.org/) and
[AdOpT-NET0](https://adopt-net0.readthedocs.io/) write, and writes what a
solved model says, in the same terms for every framework. It is a Python
package with a command line tool, depends on h5py and NumPy alone, and needs
none of the frameworks.

**Documentation:** [enerplanet.github.io/Coati](https://enerplanet.github.io/Coati)

## How it works

```bash
pip install enerplanet-coati
coati results.nc results.json calliope-v0-7-0
```

The command takes the file of a model, the JSON file to write and the
framework that wrote the file, named with its version: `calliope-v0-6-10`,
`pypsa-v1-2-4`, `adopt-net0-v0-1-10`. It writes the *results document*:

```json
{
  "schema_version": "1.0",
  "framework": "calliope",
  "framework_version": "0.7.0",
  "success": true,
  "termination_condition": "optimal",
  "objective": 15721.26,
  "timestamps": ["2005-01-01T00:00:00", "2005-01-01T01:00:00"],
  "capacities": {"north::pv": 136.35, "south::battery": 100.0},
  "generation": {"north::pv::power": 1382.45},
  "dispatch": {"pv": [0.0, 77.65]},
  "demand_timeseries": [50.0, 50.68],
  "transmission_flow": {
    "north::south": {"from": "north", "to": "south", "timeseries": [0.0, 76.09]}
  },
  "costs_by_tech": {"pv": 3.29, "gas": 15717.02},
  "costs_by_location": {"north": {"pv": 3.29}, "south": {"gas": 15717.02}},
  "tech_metadata": {"pv": {"parent": "supply", "carrier_out": "power"}}
}
```

(shortened.) A key means the same whichever framework solved the model, so a
program that reads the document need not know the frameworks. The document
holds the keys that [TEMPO](https://github.com/THD-Spatial-AI/TEMPO) reads
from the results of a model. The
[documentation](https://enerplanet.github.io/Coati/documents/results/)
describes every key, and for each framework how it follows from a file.

The framework that is named is a claim about the file, and it is checked: a
file of another framework or of another layout is refused, so that a mix-up
in a pipeline is an error and not a document full of wrong numbers. Without
a framework, or with `auto`, Coati takes it from the file.

## Supported frameworks

| Identifier | Framework | Versions | Tested with | Formats |
|---|---|---|---|---|
| `calliope-v0-6` | Calliope | 0.6.x | 0.6.10 | netCDF-4 |
| `calliope-v0-7` | Calliope | 0.7.x | 0.7.0.dev7, 0.7.0 | netCDF-4 |
| `pypsa-v0` | PyPSA | 0.25 and later 0.x | 0.25.2, 0.35.2 | netCDF-4, HDF5 |
| `pypsa-v1` | PyPSA | 1.x | 1.2.4, 1.3.0 | netCDF-4, HDF5 |
| `adopt-net0-v0-1` | AdOpT-NET0 | 0.1.x | 0.1.10 | HDF5 |

An identifier names a family, as in the table, or a version of it:
`calliope-v0-7-0`. The leading zero of a version may be left out,
`calliope-v6-10` is Calliope 0.6.10. The results are tested against what each
framework says about its own model: the SPORES and the operate mode of
Calliope, stochastic networks and several investment periods of PyPSA,
typical days and several investment periods of AdOpT-NET0.

## Installation

```bash
pip install enerplanet-coati            # the package and the command
pip install "enerplanet-coati[yaml]"    # with PyYAML, for coati dump --decode-text
```

Python 3.10 or newer is required. The package is called `enerplanet-coati`
on PyPI; the Python package and the command are `coati`.

## Command line

```bash
# the results of a model
coati results.nc results.json calliope-v0-7-0

# a folder that holds one file of results, as AdOpT-NET0 writes them; the file records
# no times, so name the first and the step
coati run/results results.json adopt-net0-v0-1-10 --time-start 2025-01-01T00:00 --time-step 1h

# to the standard output, compact, numbers rounded
coati network.h5 - pypsa-v1-2-4 --compact --decimals 3 | jq .capacities

# everything a file holds, whatever wrote it
coati dump results.nc dataset.json
coati dump results.nc flows.json --variable '/results/flow_*'

# what is this file?
coati inspect results.nc
```

| Command | Meaning |
|---|---|
| `coati [convert] SOURCE OUTPUT [FRAMEWORK]` | write the results of a model as JSON |
| `coati dump SOURCE OUTPUT` | write every group, dimension, variable and attribute of a file as JSON |
| `coati inspect SOURCE` | show the format of a file, the framework that wrote it and what it holds |
| `coati frameworks` | list the frameworks and versions that are supported |
| `coati schema {results,dataset}` | print the JSON Schema of a document |

Exit status 1 reports a conversion that failed (the message names the file
and what is wrong with it); 2 reports a usage error. A file is replaced only
once its document is complete. See the
[command line reference](https://enerplanet.github.io/Coati/usage/cli/).

## Python package

```python
import coati

document = coati.convert("results.nc", "results.json", "calliope-v0-7-0")
document["objective"]

results = coati.read_results("network.nc")  # the framework is taken from the file
results.capacities["north::pv"]
results.dispatch["pv"]  # a NumPy array, one value for each time

coati.dump("results.nc", "dataset.json")  # everything the file holds

with coati.open_dataset("results.nc") as dataset:
    dataset.groups["results"].variables["flow_cap"].read()
```

Errors derive from `coati.CoatiError`; the package is typed.

## JSON

Result files are full of `NaN` and infinities, which are no JSON. Coati
writes JSON that any parser reads: a number that is not finite becomes
`null`, or a string or an error with `--non-finite`. Numbers are written
with the digits that are needed to read them back unchanged, or rounded with
`--decimals`. See
[JSON](https://enerplanet.github.io/Coati/documents/json/).

## Development

```bash
pip install -e ".[dev]"
make test              # the test suite
make check             # lint, types and tests with coverage, what CI runs
make test-frameworks   # solve models with the frameworks that are installed
make docs              # serve the documentation
```

Or containerized: [environment/](environment/) carries a single image with
the full toolchain (Python, the test dependencies, ruff, mypy, MkDocs), the
same Make targets inside it, and `ENV=dev|test` selecting
`environment/.env.*`:

```bash
make -C environment build             # one-time image build
make -C environment check ENV=test    # tests with coverage, lint and types
make -C environment docs              # documentation on http://localhost:8000
```

The tests compare the documents with what each framework says about its own
model; [`tests/data`](tests/data/README.md) holds files that the frameworks
have written. See [CONTRIBUTING.md](CONTRIBUTING.md) for the workflow and
the commit convention.

## Citation

If you use Coati in your research, please cite it; see
[CITATION.cff](CITATION.cff).

## License

[MIT](LICENSE). Copyright (c) 2026 BigGeoData & Spatial AI, Technische Hochschule Deggendorf.
