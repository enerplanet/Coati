# Contributing

Thank you for taking the time to contribute to **Coati**.

This project welcomes bug reports, feature requests, documentation
improvements, code changes and support for further versions of the
frameworks. Please read this guide before opening an issue or submitting a
pull request.

## Code of Conduct

By participating in this project, you agree to follow the rules and
expectations described in the [Code of Conduct](CODE_OF_CONDUCT.md).

## Reporting bugs and requesting changes

Use the issue tracker for bug reports, feature requests and documentation
issues: <https://github.com/enerplanet/Coati/issues>.

When reporting a bug, please include:

- the framework and its version, and how the file was written
  (`model.to_netcdf`, `n.export_to_netcdf`, `n.export_to_hdf5`, ...)
- the command or the call, and the full message it ends with
- the output of `coati inspect FILE`, which describes the file without its
  values
- what you expected and what the document says instead; if a number is
  wrong, the number that the framework itself reports for it
- the Coati version (`coati --version`) and the Python version

A file that reproduces the problem helps most. Make it as small as you can
and remove what is confidential; `tests/models` has small models of every
framework to start from.

## Development workflow

Python 3.10 or newer and `make` are needed.

```bash
git clone https://github.com/enerplanet/Coati.git
cd Coati
python -m venv .venv && . .venv/bin/activate
make install     # the package in editable mode, with everything for development
make test        # the test suite
make check       # lint, types and tests with coverage, what CI runs
```

Without a local toolchain, the same targets run in the container described
in [environment/README.md](environment/README.md):

```bash
make -C environment build            # one-time image build
make -C environment check ENV=test   # tests with coverage, lint and types
```

`pre-commit install --hook-type pre-commit --hook-type commit-msg` runs the
checks before every commit.

### Branches and commits

Create a branch named `<type>/<description>` (see
[Branch Naming](docs/getting-started/branch-naming.md)) and write commit
messages in the Conventional Commits format (see
[Commit Conventions](docs/getting-started/commit-conventions.md)), for
example:

```
feat(pypsa): report the shadow prices of the buses
fix(reader): read attributes that are arrays of texts
docs(calliope): explain the weights of the classes of cost
```

Both are checked automatically on pull requests. Keep the history linear:
rebase on `main` instead of merging it into your branch.

### Changing how results are extracted

- The test of an extractor is what the framework says. A number of the
  results document must equal the number that the framework reports for its
  own model, through its own interface. `tests/models` holds a model of each
  framework with the *facts* about it, `tests/test_real_files.py` compares
  the documents with them, and `tests/frameworks` does so with the versions
  of the frameworks that are installed.
- Every rule of an extractor has a test on a file that is made for it, small
  enough to check by hand (`tests/support/files.py`,
  `tests/test_results_*.py`). Add a case for new behaviour, for what a file
  may lack and for the message that a file that cannot be read produces.
- The meaning of a key is the same for every framework. If a framework has
  no such quantity, the key is left out; it is not filled with something
  similar. What holds for one framework alone belongs under `details`.
- A change of what a document says is visible in `tests/data/expected`.
  After a deliberate change:

  ```bash
  make expected-update            # rewrite tests/data/expected/*.json
  git diff tests/data/expected    # review every changed line
  ```

- Update the page of the framework under `docs/frameworks/`, the schema under
  `src/coati/schemas/` if a key is added, and the changelog. A change of the
  layout of a document raises its `schema_version`; the
  [architecture page](docs/development/architecture.md) describes which
  module owns what.

### Supporting a new version of a framework

1. Install the version in an environment of its own and run
   `make test-frameworks`. If the tests pass, the version writes its files as
   the versions before it did.
2. Make its files with `python -m models.fixtures` (see
   `tests/data/README.md`), add them to `FILES` in
   `tests/test_real_files.py` and to the versions that the family lists as
   tested in `src/coati/frameworks.py`.
3. If the layout of the files has changed, the version starts a new family
   with an extractor of its own; the existing families keep reading the
   files they read.

## Pull request checklist

- [ ] `make check` passes
- [ ] new behaviour is tested, against the framework where it concerns results
- [ ] documentation and `CHANGELOG.md` are updated
- [ ] commit messages follow the convention and the branch is rebased on `main`
- [ ] no credentials or private data in examples or test data

## Licensing of contributions

By contributing to this project, you confirm that your contribution is your
own work (or that you have the right to submit it), and you agree that it will
be licensed under the same [MIT license](LICENSE) as the repository.
