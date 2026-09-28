# syntax=docker/dockerfile:1
#
# Development and test environment for Coati.
#
# One image that carries everything the repository's Make targets need:
#   * Python                 -> run the package, the coati command and the tests
#   * the test dependencies  -> netCDF4 and xarray, which write and read the files of the
#                               tests, hypothesis, jsonschema and pytest
#   * ruff and mypy          -> the checks CI runs
#   * build and twine        -> build the distributions and check them
#   * MkDocs                 -> build and serve the documentation site
#   * make and git           -> the container runs the same targets as a local checkout
#
# The repo root is bind-mounted at /src by docker-compose, so source edits are
# picked up without a rebuild; only the dependencies are baked in. The package
# is not installed: Python finds it in the checkout through PYTHONPATH.

ARG PYTHON_VERSION=3.12

FROM python:${PYTHON_VERSION}-slim-bookworm

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        make \
    && rm -rf /var/lib/apt/lists/*

# The container runs as the user of the host, who owns the bind-mounted
# checkout and has no home in the image; git, which MkDocs uses for the
# revision dates, must accept the checkout whoever runs it.
RUN git config --system --add safe.directory /src
ENV HOME=/tmp

# Install what the package and its development depend on, from the metadata
# of the project: the project is installed from a stub and removed again, its
# dependencies stay. The layer is rebuilt when pyproject.toml changes. Paths
# are relative to the build context, the repo root (compose sets context: ..).
WORKDIR /build
COPY pyproject.toml README.md LICENSE ./
COPY src/coati/_version.py src/coati/_version.py
RUN touch src/coati/__init__.py \
    && pip install ".[dev]" \
    && pip uninstall --yes enerplanet-coati \
    && rm -rf /build

# The package and the command, from the checkout.
ENV PYTHONPATH=/src/src
RUN printf '#!/bin/sh\nexec python -m coati "$@"\n' > /usr/local/bin/coati \
    && chmod +x /usr/local/bin/coati

WORKDIR /src
EXPOSE 8000

# Default: the test suite via the project Makefile, so the container runs the
# same commands as a local checkout. Compose overrides the command per service
# (lint, docs, shell, the coati command).
CMD ["make", "test"]
