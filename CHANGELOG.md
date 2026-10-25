# Changelog

All notable changes to Coati are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versioning
follows [SemVer](https://semver.org/). The layout of the two documents that
Coati writes has a version of its own, `schema_version`; a change of a
document is listed under "Changed" with the keys concerned. Before 1.0, a
minor release may change the Python interface and the command line.

## [Unreleased]

### Added

- The results document, schema version 1.1, says more of what a solved
  model says, in the same terms for every framework: `storage_levels`, the
  energy each store holds at each time; `prices`, the marginal price of each
  carrier at each location at each time, where the file holds it, which PyPSA
  records for every bus and Calliope 0.7 if the model asks for the shadow
  price of its balance; `fixed_costs_by_location` and
  `variable_costs_by_location`, the cost told into what is paid for having
  the capacity and what is paid for operating it; `emissions_by_location` and
  `total_emissions`, as each framework records them; and `curtailment`, what
  a generator could have put out from its resource but did not, where the
  file records the resource. Nothing a reader of 1.0 relies on has changed,
  and the schema of 1.0 stays published next to that of 1.1.
- PyPSA: `details.global_constraints`, the limits of the network such as a
  cap on emissions, with the defaults PyPSA leaves out of a file and the
  shadow price `mu`.
- Calliope: the figures that Calliope computes from the solution, under
  `details`: the cost of every class as the file has it, the systemwide
  capacity factors and levelised costs, the total levelised cost, the total
  generation and the use of the sources (0.7) or the resources (0.6), and the
  supply that was not used (0.7).

## [0.2.0-alpha] - 2026-10-25

Coati reads every result file that
[MEME](https://github.com/enerplanet/meme) 0.2.0-alpha produces, the power
flows among them: every scenario and example of MEME 0.2.0-alpha, run on
every target that accepts it, gives a document that agrees with what the
framework itself reports for the file.

### Added

- PyPSA: the solution of a power flow. A network that `n.pf()` or `n.lpf()`
  solved has no objective and no costs; its document reports the capacities
  that were given and the dispatch as solved, and `details.power_flow` holds
  the slack buses, the voltage of every bus, the reactive power of every
  generator and storage unit and the loading of every line and transformer.
  The convergence is taken from `power_flow/convergence.csv` next to the
  network, as MEME writes it: `termination_condition` is `converged` or
  `not_converged`, and `unknown` without a record.
- The page *With MEME* describes the bundles of MEME 0.2.0-alpha, the mode
  `power_flow` and how an energy-sized storage, a copperplate, demand that is
  not met and a priced line of MEME appear in a document.
- The file `pypsa-1.2.4-power-flow.nc` under `tests/data`, an electrical
  network that PyPSA 1.2.4 solved by a power flow, with the facts of PyPSA.

### Changed

- PyPSA: a bus named `north::electricity` carries `electricity` whatever its
  attribute `carrier` says, as the documentation promised; a further part of
  the name, as in `north::electricity::battery`, tells buses apart. (Keys of
  `generation` and `carrier_out` of `tech_metadata`.)
- PyPSA: a generator whose carrier or name is `unmet` stands for demand that
  is not met, as one named `unmet_demand` does.
- A technology whose output stays below 1e-6 at every time is left out of
  `dispatch`, like one that puts out nothing.

### Fixed

- PyPSA: a committable unit that was never off has no series `status` in the
  file, since the default of the status is on, and its stand-by cost was
  counted as nothing. It is counted for every snapshot now.

## [0.1.0-alpha] - 2026-10-25

The first pre-release. It reads every result file that
[MEME](https://github.com/enerplanet/meme) 0.1.0-alpha produces: every
scenario and example of MEME, run on every target that accepts it, gives a
document that agrees with what the framework itself reports for the file.

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
  committable units, networks with several investment periods and stochastic
  networks; and of AdOpT-NET0 0.1, including typical days and several
  investment periods.
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
- Tests against files that the frameworks have written, of Calliope 0.6.8, 0.6.10,
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

[Unreleased]: https://github.com/enerplanet/Coati/compare/v0.2.0-alpha...HEAD
[0.2.0-alpha]: https://github.com/enerplanet/Coati/releases/tag/v0.2.0-alpha
[0.1.0-alpha]: https://github.com/enerplanet/Coati/releases/tag/v0.1.0-alpha
