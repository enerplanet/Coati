# Testing

```console
$ pip install -e ".[dev]"
$ make test        # the test suite
$ make check       # lint, types and tests with coverage, what CI runs
```

| Target | Runs |
|---|---|
| `make test` | the test suite |
| `make cover` | the test suite with coverage; fails below 95 % |
| `make lint` | ruff: the rules and the format |
| `make typecheck` | mypy in strict mode |
| `make check` | `lint`, `typecheck` and `cover` |
| `make test-frameworks` | the tests that solve models with the frameworks that are installed |
| `make expected-update` | rewrites the expected documents |
| `make docs-build` | the documentation, as CI builds it |
| `make build` | the source distribution and the wheel |

The same targets run in a container: `make -C environment check ENV=test`.

## What is tested against what

A converter is right if its documents say what the files say, and the files
say what the frameworks mean. The tests therefore compare Coati with
something that knows better, at each step:

| What | is compared with |
|---|---|
| the readers | the netCDF library, xarray and SciPy: every variable of every file |
| the interpretation of values | the netCDF library, for times |
| the parser of YAML | PyYAML |
| the results | what each framework says about its own model |
| the documents | their JSON Schemas |
| the JSON | the parser of the standard library, which reads what Coati writes |

### Files made for the tests

`tests/support/files.py` writes files as the frameworks write them, small
enough to check every number by hand: two locations, three times, four
technologies. Each rule of an extractor has a test on such a file:

```python
def test_generation_counts_each_time_with_its_weight(solved: dict) -> None:
    assert solved["generation"] == {
        "a::pv::power": 6 + 2 * 8 + 4,
        ...
    }
```

The expected number is spelled out, so that a reader of the test sees where
it comes from.

### Files that the frameworks have written

`tests/data` holds the files of a model that each framework has solved:

| Framework | Versions |
|---|---|
| Calliope | 0.6.10, 0.7.0.dev7, 0.7.0; each with a run in the SPORES mode |
| PyPSA | 0.25.2, 0.35.2, 1.2.4, 1.3.0; each as netCDF and as HDF5 |
| AdOpT-NET0 | 0.1.10; also with typical days and with two investment periods |

Next to a file lie its *facts*: what the framework says about the model
through its own interface, such as `n.statistics` of PyPSA or
`model.results` of Calliope, written down by the script that solved the
model. `tests/test_real_files.py` compares the documents with the facts.
The document is made from the file alone, the facts without the file; where
they agree, the file was read as the framework means it.

The models are defined in `tests/models`, and
[`tests/data/README.md`](https://github.com/enerplanet/Coati/blob/main/tests/data/README.md)
tells how to make the files anew.

### Expected documents

`tests/data/expected` holds the documents of the files as Coati has written
them. A change of what a document says fails a test, so that it does not go
unnoticed. After a change that is meant:

```console
$ make expected-update
$ git diff tests/data/expected
```

### The frameworks themselves

`tests/frameworks` solves the models with the frameworks that are
installed, converts what they write and compares the documents with the
facts. These tests tell when a new version of a framework writes its files
differently. They are skipped where a framework or a solver is missing, so
the test suite runs without them.

```console
$ python -m venv .venv-pypsa && . .venv-pypsa/bin/activate
$ pip install "pypsa[hdf5]" -e ".[test]"
$ make test-frameworks
```

| Framework | Install | Solver |
|---|---|---|
| PyPSA | `pip install "pypsa[hdf5]"` | HiGHS, which comes with PyPSA |
| Calliope 0.7 | `pip install calliope` | CBC or GLPK |
| AdOpT-NET0 | `pip install adopt-net0 "tsam<3"` | GLPK |

PyPSA exports to HDF5 with PyTables, which it installs with its extra `hdf5`
alone. Calliope 0.6 needs a version of Python that Coati does not support,
so the two cannot be installed together. Its files are tested from
`tests/data` alone.

### Properties

The tests of the writer and of the readers state properties that hold for
any input, and [Hypothesis](https://hypothesis.works/) looks for an input
that breaks them: what is written as JSON is read back as the same values;
a file that is cut off at any byte is refused with an error of Coati and
not with one of Python.

## Warnings are errors

The test suite turns warnings into errors. A deprecation in NumPy or h5py
fails a test when it appears, and not when the deprecated behaviour is
removed.

## Coverage

The coverage of the package must not fall below 95 %, counting branches.
What is not covered are branches for files that the frameworks do not
write, as far as is known.

## CI

Every pull request runs:

| Job | Checks |
|---|---|
| lint | ruff and mypy |
| test | the test suite on Python 3.10 to 3.14 on Linux, and on macOS and Windows |
| oldest | the test suite with the oldest versions of the dependencies that the package allows |
| frameworks | the tests of `tests/frameworks` with the current versions of PyPSA, Calliope and AdOpT-NET0 |
| build | the distributions: their metadata, the content of the wheel, the command of the installed package |
| environment | the test suite and the checks inside the image of `environment/` |
| docs | the documentation; a warning is an error |
