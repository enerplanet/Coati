# Attributions

Coati depends on two libraries at run time, and on a third if asked for:

| Component | Source | License | Use |
|---|---|---|---|
| h5py, with the HDF5 library it ships | <https://www.h5py.org/> | BSD-3-Clause | reading netCDF-4 and HDF5 files |
| NumPy | <https://numpy.org/> | BSD-3-Clause | arrays |
| PyYAML (optional, the extra `yaml`) | <https://pyyaml.org/> | MIT | `coati dump --decode-text` for the YAML that Calliope stores in attributes |

Used to build, test and document the package, and not part of it:

| Component | Source | License | Use |
|---|---|---|---|
| Hatchling | <https://hatch.pypa.io/> | MIT | build backend |
| pytest, pytest-cov | <https://pytest.org/> | MIT | test runner and coverage |
| Hypothesis | <https://hypothesis.works/> | MPL-2.0 | property tests |
| jsonschema | <https://python-jsonschema.readthedocs.io/> | MIT | validation of the documents against their schemas |
| netCDF4, with the netCDF library it ships | <https://unidata.github.io/netcdf4-python/> | MIT | writes the files of the tests; the reader is compared with it |
| xarray | <https://xarray.dev/> | Apache-2.0 | the reader is compared with it |
| SciPy | <https://scipy.org/> | BSD-3-Clause | the reader of the classic formats is compared with it |
| ruff | <https://docs.astral.sh/ruff/> | MIT | lint and format |
| mypy | <https://mypy-lang.org/> | MIT | type check |
| MkDocs | <https://www.mkdocs.org/> | BSD-2-Clause | documentation site generator |
| Material for MkDocs | <https://squidfunk.github.io/mkdocs-material/> | MIT | documentation theme |
| mkdocstrings | <https://mkdocstrings.github.io/> | ISC | reference of the Python package |
| Spatial AI logos in `docs/assets/logos/` | BigGeoData & Spatial AI, Technische Hochschule Deggendorf | project assets | documentation branding |

## The frameworks

Coati reads the files of three frameworks and includes no code of any of
them:

| Framework | Source | License |
|---|---|---|
| Calliope | <https://github.com/calliope-project/calliope> | Apache-2.0 |
| PyPSA | <https://github.com/PyPSA/PyPSA> | MIT |
| AdOpT-NET0 | <https://github.com/UU-ER/AdOpT-NET0> | MIT |

The files under `tests/data` were written by these frameworks from models
that belong to this repository (`tests/models`); `tests/data/README.md`
tells how. The models use technologies of the library of AdOpT-NET0
(`Photovoltaic`, `WindTurbine_Onshore_1500`, `Storage_Battery`,
`electricitySimple`), whose names and parameters appear in the files.

The keys of the results document are those that
[TEMPO](https://github.com/THD-Spatial-AI/TEMPO) reads from the results of a
model, and the extraction started from the scripts of
[MEME](https://github.com/enerplanet/meme) (MIT) that made such results for
Calliope and AdOpT-NET0.
