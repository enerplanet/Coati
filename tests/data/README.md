# Test data

Files that the frameworks themselves have written, for the tests in
`tests/test_real_files.py`. Each holds a small model of two locations, `north`
and `south`, that has every kind of technology the results document knows:
supply, demand, storage, conversion and transmission.

| File | Written by | Holds |
| --- | --- | --- |
| `adopt-net0-0.1.10.h5` | AdOpT-NET0 0.1.10 | the model, 48 hours |
| `adopt-net0-0.1.10-typical-days.h5` | AdOpT-NET0 0.1.10 | six days, for which two typical days stand (method 1) |
| `adopt-net0-0.1.10-periods.h5` | AdOpT-NET0 0.1.10 | two investment periods |
| `calliope-0.6.10.nc` | Calliope 0.6.10 | the model, 24 hours |
| `calliope-0.6.10-spores.nc` | Calliope 0.6.10 | the optimum and two SPORES |
| `calliope-0.7.0.dev7.nc` | Calliope 0.7.0.dev7 | the model, 24 hours |
| `calliope-0.7.0.dev7-spores.nc` | Calliope 0.7.0.dev7 | the optimum and two SPORES |
| `calliope-0.7.0.nc` | Calliope 0.7.0 | the model, 24 hours |
| `calliope-0.7.0-spores.nc` | Calliope 0.7.0 | the optimum and two SPORES |
| `pypsa-0.25.2.nc`, `.h5` | PyPSA 0.25.2 | the network in both formats, 24 snapshots that count twice |
| `pypsa-0.35.2.nc`, `.h5` | PyPSA 0.35.2 | the network in both formats |
| `pypsa-1.2.4.nc`, `.h5` | PyPSA 1.2.4 | the network in both formats |
| `pypsa-1.2.4-stochastic.nc` | PyPSA 1.2.4 | a network with two scenarios |
| `pypsa-1.2.4-unsolved.nc` | PyPSA 1.2.4 | the network before it is optimised |
| `pypsa-1.3.0.nc`, `.h5` | PyPSA 1.3.0 | the network in both formats |

## Compression

The files are compressed with xz and have the ending `.xz`. The tests unpack
them into a temporary directory. Compressed, the files take a tenth of the
space, and the repository needs no Git LFS for them, through which it routes
files that end in `.h5`.

## Facts

Next to a file lies `<name>.facts.json`: what the framework says about the
model through its own interface, such as `n.statistics` of PyPSA or
`model.results` of Calliope, written down by the script that solved the model.
A results document must say the same, although Coati makes it from the file
alone, without the framework. AdOpT-NET0 keeps nothing of a solved model but
the file; its facts are read with the function AdOpT-NET0 offers for that and
checked against the figures of the summary.

A key of the facts that starts with an underscore is a note for one test and no
key of the results document.

## Expected documents

`expected/<name>.json` is the results document of a file as Coati has written
it. The tests compare the documents that Coati writes now with these, so that
a change of the documents does not go unnoticed. After a change that is meant,
write them anew and review the difference:

```console
$ python -m pytest tests/test_real_files.py --update-expected
$ git diff tests/data/expected
```

## Making the files anew

The models are defined in `tests/models`. To make the files of a framework,
install the framework and a solver in an environment of their own, and run
from the directory `tests`:

```console
$ python -m models.fixtures pypsa data
$ python -m models.fixtures calliope data
$ python -m models.fixtures adopt-net0 data
```

The names of the files carry the version of the framework that is installed,
so the files of several versions lie side by side. The scripts need nothing of
Coati and run on Python 3.9, which Calliope 0.6 requires.

| Framework | Installed with | Solver |
| --- | --- | --- |
| PyPSA | `pip install "pypsa[hdf5]==1.2.4"` | HiGHS, which comes with PyPSA |
| PyPSA 0.25 | `pip install pypsa==0.25.2 linopy==0.2.6 highspy "numpy<2" "pandas<2.1" "xarray<2023.13"` | HiGHS |
| Calliope 0.7 | `pip install calliope==0.7.0` | CBC |
| Calliope 0.6 | `pip install calliope==0.6.10` on Python 3.9 | CBC |
| AdOpT-NET0 | `pip install adopt-net0==0.1.10 "tsam<3"` | GLPK |

A solver finds the same optimum every time, but where several solutions cost
the same it may find another one of them, and the files record when they were
written. Files that are made anew therefore differ from those they replace,
and the expected documents have to be written anew with them.
