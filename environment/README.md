# `environment/` — containerized development and test

A single image that carries everything needed to **test**, **lint**,
**build** and **document** Coati, so a checkout needs nothing but Docker:

| Layer | What |
|---|---|
| Python 3.12 (3.10 for `ENV=test`) | run the package, the `coati` command and the tests |
| the extras `test`, `lint`, `docs` and `yaml` of `pyproject.toml` | netCDF4 and xarray, which write and read the files of the tests, hypothesis, jsonschema, pytest, ruff, mypy, MkDocs with Material and mkdocstrings |
| build, twine | build the source distribution and the wheel, and check them |
| GNU make, git | the container runs the same Make targets as a local checkout |

The repo root is bind-mounted at `/src`, so source edits are picked up without
rebuilding the image. Only the dependencies are baked in; the package itself
is found in the checkout through `PYTHONPATH`. Rebuild the image only when
`pyproject.toml` or the Dockerfile change.

The frameworks are not part of the image: Coati reads their files without
them. The tests that solve models with the frameworks
(`make test-frameworks`) need an environment of their own; see
[Testing](../docs/development/testing.md).

## Setup

Prerequisites: **Docker with compose v2** and GNU `make`; everything else
lives inside the image. From the repo root (or inside `environment/`,
dropping the `-C environment`):

```bash
make -C environment build ENV=dev   # one-time image build
make -C environment test  ENV=dev   # the test suite inside the container
```

## Usage

The targets live in this folder's [`Makefile`](Makefile): run them **inside
`environment/`** as plain `make <target>`, from the repo root as
`make -C environment <target>`, or through the root Makefile's shorthand
`make env-<target>`:

```bash
# from the repo root:
make -C environment build ENV=dev   # image (Python, test dependencies, ruff, mypy, MkDocs)
make -C environment test  ENV=dev   # pytest inside the container
make -C environment lint  ENV=dev   # ruff and mypy
make -C environment check ENV=test  # tests with coverage on the oldest Python, then lint: what CI runs
make -C environment docs  ENV=dev   # documentation with live reload on http://localhost:8000
make -C environment cli   ARGS="results.nc results.json calliope-v0-7-0"
make -C environment shell ENV=dev   # python, coati, pytest, ruff, mypy, mkdocs, make, git
make -C environment clean ENV=dev   # remove containers and image
```

`cli` runs the `coati` command straight from the working tree, so it reflects
uncommitted changes; paths in `ARGS` are relative to the repo root, which the
container sees as `/src`. To write a document to the standard output, drive
compose directly with `-T`:

```bash
docker compose --env-file environment/.env.dev -f environment/docker-compose.yml \
  run --rm -T coati results.nc - --compact > results.json
```

## Per-environment settings (dev / test)

Coati has no runtime configuration or credentials; the env files only shape
how the tools run. Select one with `ENV=` on any of this folder's Make targets
(defaults to `dev`).

| Variable | `.env.dev` | `.env.test` | Meaning | Used by |
|---|---|---|---|---|
| `COMPOSE_PROJECT_NAME` | `coati-env` | `coati-env` | compose project (containers) | compose |
| `IMAGE_TAG` | `coati-env:dev` | `coati-env:test` | tag of the environment image | compose |
| `PYTHON_VERSION` | 3.12 | 3.10 | version of Python of the image | compose → `Dockerfile` |
| `TEST_TARGET` | `test` | `cover` | root Makefile target the `test` service runs | compose → root `Makefile` |
| `PYTEST_ADDOPTS` | empty | `-p no:cacheprovider` | options for every run of pytest | pytest inside the container |
| `DOCS_PORT` | 8000 | 8000 | host port the `docs` service publishes | compose |

`dev` is for iterating: a current Python, the plain suite, the docs server.
`test` reproduces CI on the oldest Python that Coati supports: the suite with
coverage, which fails below 95 %, and no cache between runs. Copy either
file to add another environment (say `.env.py314` with `PYTHON_VERSION=3.14`)
and select it with `ENV=py314`.

Or drive compose directly with `--env-file`:

```bash
HOST_UID=$(id -u) HOST_GID=$(id -g) docker compose --env-file environment/.env.test \
  -f environment/docker-compose.yml run --rm test
```

## Notes

- The containers run as the user who runs `make`: `HOST_UID` and `HOST_GID`
  are set by the Makefile, and what a container writes into the checkout
  (`dist/` from `make -C environment cli` or `build`, `coverage.xml`, the
  caches of the tools) belongs to that user. Without them, as when compose
  is driven directly, the containers run as root.
- `docs` serves with live reload; `make docs-build`, the strict build that
  CI's docs workflow relies on, runs in `make -C environment shell`.
- The image copies only `pyproject.toml`, `README.md`, `LICENSE` and
  `src/coati/_version.py` at build time (see the root `.dockerignore`);
  every other file comes from the bind mount.
- CI builds this image and runs `make -C environment check ENV=test` in it,
  so the environment cannot drift from the toolchain the tests expect.
