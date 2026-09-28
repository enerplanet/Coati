# Python package

```python
import coati
```

The functions come in pairs. One of each pair returns a document as a
dictionary, the other writes it as JSON:

| Returns | Writes | Document |
|---|---|---|
| [`results_document`][coati.api.results_document] | [`convert`][coati.api.convert] | what a solved model says |
| [`dataset_document`][coati.api.dataset_document] | [`dump`][coati.api.dump] | everything a file holds |

[`read_results`][coati.api.read_results] returns the results as an object,
[`inspect`][coati.api.inspect] summarises a file, and
[`detect`][coati.api.detect] tells which framework wrote it. The
[reference](../reference/functions.md) describes every argument.

## Results

```python
import coati

document = coati.convert("results.nc", "results.json", "calliope-v0-7-0")
```

`convert` writes the file and returns the document that it has written. The
framework is an identifier as on the command line; without it, the
framework is taken from the file.

`results_document` returns the document without writing it. The document is
a dictionary whose time series are NumPy arrays:

```python
document = coati.results_document("results.nc")

document["capacities"]["north::pv"]  # 136.3509
document["dispatch"]["pv"].max()  # 136.3509
document["timestamps"][0]  # '2005-01-01T00:00:00'
```

`read_results` returns a [`Results`][coati.results.document.Results] object
with the same content as attributes, for a program that goes on to compute:

```python
results = coati.read_results("results.nc", "calliope-v0-7-0")

results.framework.version  # '0.7.0'
results.success  # True
results.capacities["north::pv"]  # 136.3509
results.total(results.dispatch["pv"])  # the generation, each time with its weight

for pair, exchange in results.transmission_flow.items():
    print(pair, exchange.origin, exchange.destination, exchange.timeseries.sum())
```

### Options

[`ExtractOptions`][coati.results.options.ExtractOptions] holds the choices
about the content, [`JsonOptions`][coati.jsonio.JsonOptions] those about the
JSON:

```python
from coati import ExtractOptions, JsonOptions

coati.convert(
    "run/results",  # a directory that holds one file
    "results.json",
    "adopt-net0-v0-1-10",
    options=ExtractOptions(time_start="2025-01-01T00:00", time_step="1h"),
    json_options=JsonOptions(indent=None, decimals=3),
)
```

## Everything a file holds

```python
from coati import DumpOptions

coati.dump("results.nc", "dataset.json")
coati.dump("results.nc", "flows.json", DumpOptions(variables=("/results/flow_*",)))

document = coati.dataset_document("results.nc", DumpOptions(data=False))
document["groups"]["results"]["variables"]["flow_cap"]["dimensions"]
# ['nodes', 'techs', 'carriers']
```

`dump` reads the values of a variable when it writes the variable, so that
it needs the memory of the largest variable alone. `dataset_document`
returns the whole document and needs the memory of the whole file.

## Writing to a stream

The output of `convert` and `dump` is a path or a stream that is open for
writing text:

```python
import sys

coati.convert("results.nc", sys.stdout, json_options=JsonOptions(indent=None))
```

A document that a program has changed is written with the functions of
[`coati.jsonio`][coati.jsonio], which know NumPy arrays and the numbers that
are no JSON:

```python
from coati import jsonio

document = coati.results_document("results.nc")
document["scenario"] = "reference"
jsonio.write_file(document, "results.json", JsonOptions(decimals=3))
text = jsonio.dumps(document)
```

## Reading a file

[`open_dataset`][coati.readers.open_dataset] opens a netCDF or HDF5 file as
a tree of groups, dimensions and variables, the model that both documents
are made from:

```python
with coati.open_dataset("results.nc") as dataset:
    dataset.format  # 'netcdf4'
    results = dataset.groups["results"]
    flow = results.variables["flow_cap"]
    flow.dimensions, flow.shape  # ('nodes', 'techs', 'carriers'), (2, 7, 2)
    values = flow.read()  # the values as stored

    for group in dataset.walk():
        print(group.path, list(group.variables))
```

`read` returns the values as the file stores them.
[`coati.cf.decode`][coati.cf.decode] interprets them according to the CF
conventions: times, missing values, packed numbers.

## Frameworks

```python
found = coati.detect("network.nc")
found.id, found.title, found.version  # ('pypsa-v1-2-4', 'PyPSA', '1.2.4')
found.family.id  # 'pypsa-v1'

for family in coati.FAMILIES:
    print(family.id, family.versions, family.tested)
```

`detect` returns `None` for a file that no framework that Coati knows has
written.

## Errors

Every error that Coati raises is a [`CoatiError`][coati.errors.CoatiError]:

| Error | Raised if |
|---|---|
| [`SourceError`][coati.errors.SourceError] | a file cannot be read: it does not exist, is no netCDF or HDF5 file or is damaged |
| [`FrameworkError`][coati.errors.FrameworkError] | an identifier is invalid, or the file was not written by the framework that it names |
| [`ExtractionError`][coati.errors.ExtractionError] | a file lacks what the results require, or holds it in another form |
| [`EncodingError`][coati.errors.EncodingError] | a value cannot be written as JSON |

```python
from coati.errors import CoatiError, FrameworkError

try:
    coati.convert(source, output, framework)
except FrameworkError as error:
    ...  # the file is not what the pipeline took it for
except CoatiError as error:
    ...  # the message names the file and what is wrong with it
```

Writing the output may raise an `OSError`, as writing any file may.

## Warnings

What a reader of a document should know about its making is part of the
document, under `warnings`. The functions also log each warning to the
logger `coati`. The package decides nothing about where the messages go; a
program that wants to see them configures logging:

```python
import logging

logging.basicConfig(level=logging.WARNING)
```

## Types

The package is typed and says so with a `py.typed` marker; a type checker
checks the calls of a program that uses it.
