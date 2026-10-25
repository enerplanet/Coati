# With MEME

[MEME](https://github.com/enerplanet/meme) takes one canonical model, writes
it in the native form of PyPSA, Calliope and AdOpT-NET0, runs the solvers and
returns the results of every run in one bundle. Coati reads the result files
of such a bundle and makes the same document of each, whichever framework
solved the model.

## The targets of MEME and the identifiers of Coati

MEME names a framework and a version as a *target*; Coati names them with a
framework identifier. For MEME 0.1.0-alpha:

| MEME target | Framework | Identifier for Coati | Result file |
|---|---|---|---|
| `pypsa` | PyPSA 1.2.4 | `pypsa-v1-2-4` | `output/network.nc` |
| `calliope`, alias `calliope-0.7` | Calliope 0.7.0 | `calliope-v0-7-0` | `output/results.nc` |
| `calliope-0.6` | Calliope 0.6.8 | `calliope-v0-6-8` | `output/results.nc` |
| `adopt-net0` | AdOpT-NET0 0.1.10 | `adopt-net0-v0-1-10` | `input/results/<time of the run>/optimization_results.h5` |

`GET /capabilities` of a running MEME lists its targets with the version
behind each, so a pipeline can form the identifier from the answer: the
name of the framework, `-v` and the version with its dots replaced by
hyphens. Naming the identifier is worth the trouble for the two frameworks
whose files do not record their version, AdOpT-NET0 and Calliope 0.7.0: the
document then states it.

## The bundle

`GET /jobs/{id}` returns a zip. Unpacked, it holds the log, the submitted
configuration, a `results.json` with the state of every run, and under
`files/` the directory of each run:

```text
files/
  run_0/
    input/      what MEME wrote for the framework
    output/     what the framework wrote: results.nc, network.nc, ...
  run_1/        the next run of a sweep
```

A job that ran several targets at once has one such tree per target. The
result file of a run is what Coati converts:

```console
$ coati files/run_0/output/results.nc results.json calliope-v0-7-0
```

For AdOpT-NET0, which writes its results into a folder named after the time
of the run, name the folder above the file: Coati takes the one data file it
finds in it.

```console
$ coati files/run_0/input/results results.json adopt-net0-v0-1-10
```

### Runs with several files

Two kinds of runs write more than one result file into one folder. Coati
refuses a folder that holds several, and its message lists them; name the
file that is wanted.

- In PyPSA's mode `alternatives`, `output/` holds `network_baseline.nc`, the
  optimum, next to `network.nc`, the alternative. The alternative was
  optimised with an objective of its own, and its document says so in a
  warning: its `objective` is what the system costs, its
  `objective_function_value` what the network recorded.
- In AdOpT-NET0's modes `pareto` and `monte_carlo`, the results folder holds
  one folder for each point of the front or each draw. Each is a file that
  Coati reads.

### What the modes of MEME look like in a document

| Mode of MEME | In the document |
|---|---|
| `plan`, `operate` | the results; in the operate mode of Calliope the capacities are the parameters that were given |
| `alternatives` | Calliope: the first of the SPORES, the others under `details.spores`, with a warning; PyPSA: see above |
| `stochastic` (PyPSA) | the expectation over the scenarios, `scenarios` with their probabilities, and a warning |
| a sweep | one run and one document per point; `config.json` of the bundle names the assignments |
| `time_aggregation` with typical days | AdOpT-NET0: the series of the whole time; Calliope 0.6: the clustered days, with `weights` |
| `time_aggregation` with `resample` | Calliope: one time for each resampled step, with the flows of the whole step |

Before a release of Coati, every scenario and example of MEME is run on
every target that accepts it, and every document is compared with what the
framework itself says about the solved model, as the
[tests](../development/testing.md#the-runs-of-meme) describe. For MEME
0.1.0-alpha the documents of all 172 result files agree.
