# Installation

Coati needs Python 3.10 or newer.

```console
$ pip install enerplanet-coati
```

The package is called `enerplanet-coati` on PyPI. The Python package it
installs is `coati`, and so is the command:

```console
$ coati --version
coati 0.1.0a0
```

`0.1.0a0` is how Python writes the version `0.1.0-alpha`. pip installs an
alpha version if there is no other; once there are releases, `--pre` asks
for the versions before a release.

`python -m coati` runs the same command where the directory of the scripts is
not on the search path.

## Dependencies

| Package | Needed for |
|---|---|
| [h5py](https://www.h5py.org/) 3.8 or newer | reading netCDF-4 and HDF5 files |
| [NumPy](https://numpy.org/) 1.23 or newer | arrays |

Both come as wheels for the common platforms and bring the HDF5 library with
them; nothing has to be compiled. The classic netCDF formats are read without
any library.

Coati does not need Calliope, PyPSA or AdOpT-NET0, nor xarray, pandas or the
netCDF library. It can be installed where a framework cannot, such as next to
another version of the framework or on a version of Python that the
framework does not support.

## Optional: YAML

Calliope stores its configuration as YAML in the attributes of a file.
`coati dump --decode-text` writes such attributes as documents instead of as
text, which needs [PyYAML](https://pyyaml.org/):

```console
$ pip install "enerplanet-coati[yaml]"
```

The results document does not need PyYAML: the few values that it takes from
the configuration are read by a parser of Coati's own.

## From source

```console
$ git clone https://github.com/enerplanet/Coati.git
$ cd Coati
$ pip install .
```

For development, install the package in editable mode with the tools; see
[Testing](../development/testing.md):

```console
$ pip install -e ".[dev]"
```

## In a container

The repository has an image with everything for development, which also runs
the command without an installation on the host:

```console
$ make -C environment build
$ make -C environment cli ARGS="results.nc results.json calliope-v0-7-0"
```

Paths are relative to the root of the repository; see
[`environment/README.md`](https://github.com/enerplanet/Coati/blob/main/environment/README.md).
