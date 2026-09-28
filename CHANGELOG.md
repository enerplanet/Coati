# Changelog

All notable changes to Coati are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versioning
follows [SemVer](https://semver.org/). The layout of the two documents that
Coati writes has a version of its own, `schema_version`; a change of a
document is listed under "Changed" with the keys concerned. Before 1.0, a
minor release may change the Python interface and the command line.

## [Unreleased]

### Added

- The Coati identity: the banner on the README and the docs landing page
  (light and dark), the mark as the docs logo and the kit's favicon; the
  artwork lives under `docs/assets/logos/`.
- The `coati` command: `coati SOURCE OUTPUT [FRAMEWORK]` writes the results
  of a solved model as JSON. The framework is named together with its
  version, as in `calliope-v0-6-10`, `pypsa-v1-2-4` or `adopt-net0-v0-1-10`,
  or taken from the file. Further commands write everything a file holds
  (`dump`), summarise a file (`inspect`), list what is supported
  (`frameworks`) and print the JSON Schema of a document (`schema`).
- The Python package `coati` with the same functions: `convert`,
  `results_document`, `read_results`, `dump`, `dataset_document`, `inspect`,
  `detect` and `open_dataset`. The package is typed.
- The results document, schema version 1.0: capacities, generation,
  dispatch, demand, demand that is not met, the exchange between locations,
  costs by technology and location and the kinds of the technologies, in the
  same terms for every framework. It holds the keys that TEMPO reads from the
  results of a model.
- Results of Calliope 0.6 and 0.7, including the SPORES and the operate
  mode; of PyPSA 0.25 and later, from netCDF and from HDF5, including
  networks with several investment periods and stochastic networks; and of
  AdOpT-NET0 0.1, including typical days and several investment periods.
- The dataset document, schema version 1.0: the groups, dimensions,
  variables and attributes of any netCDF or HDF5 file, with the values read
  according to the CF conventions: times, missing values, packed numbers,
  truth values and texts.
- Readers for netCDF-4 and HDF5, on top of h5py, and for the classic netCDF
  formats CDF-1, CDF-2 and CDF-5, which need no library. Coati does not need
  the netCDF library, xarray, pandas or any of the frameworks.
- A writer of strict JSON: numbers that are not finite become `null`, a
  string or an error, as the caller chooses; large arrays are written in
  pieces; a file is replaced only once its document is complete.
- JSON Schemas of both documents, shipped with the package.
- Tests against files that the frameworks have written, of Calliope 0.6.10,
  0.7.0.dev7 and 0.7.0, of PyPSA 0.25.2, 0.35.2, 1.2.4 and 1.3.0 and of
  AdOpT-NET0 0.1.10, which compare the documents with what each framework
  says about its model through its own interface; tests that solve the models
  anew with the frameworks that are installed; and tests of the readers
  against the netCDF library, xarray and SciPy.
- CI (lint, types, tests on Python 3.10 to 3.14 and on three operating
  systems, the oldest versions of the dependencies, the frameworks, the
  distributions), a release workflow that publishes to PyPI, and the MkDocs
  documentation site.
- `environment/`: a containerized development and test environment with
  compose services for the tests, the checks, the docs server, the `coati`
  command and a shell, selected with `ENV=dev|test`.
