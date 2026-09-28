PYTHON ?= python

# The same targets run inside a container with the full toolchain (Python, the
# netCDF and HDF5 libraries, MkDocs) from environment/: `make -C environment help`,
# or the env-<target> shorthand below, e.g. `make env-test ENV=test`.

.DEFAULT_GOAL := help
.PHONY: install test test-frameworks cover lint fmt typecheck check expected-update docs docs-build build clean help

help: ## Show this help
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'
	@echo "  env-<target>     run a target of environment/Makefile (build, test, lint, check, docs, cli, shell, clean)"

install: ## Install the package in editable mode with everything for development
	$(PYTHON) -m pip install -e ".[dev]"

test: ## Run the test suite
	$(PYTHON) -m pytest

test-frameworks: ## Run the tests that solve models with the frameworks that are installed
	$(PYTHON) -m pytest -m frameworks tests/frameworks

cover: ## Run the test suite and report the coverage; fails below 95 %
	$(PYTHON) -m pytest --cov --cov-report=term-missing --cov-report=xml

lint: ## Check the style of the code and of its formatting
	ruff check .
	ruff format --check .

fmt: ## Format the code in place and fix what can be fixed
	ruff format .
	ruff check --fix .

typecheck: ## Check the types
	mypy

check: lint typecheck cover ## Lint, types and tests with coverage, what CI runs

expected-update: ## Rewrite tests/data/expected after a deliberate change of the documents
	$(PYTHON) -m pytest tests/test_real_files.py --update-expected
	@echo "review the change with: git diff tests/data/expected"

docs: ## Serve the documentation with live reload (needs the extra `docs` installed)
	mkdocs serve

docs-build: ## Build the documentation as CI does; a warning is an error
	mkdocs build --strict

build: ## Build the source distribution and the wheel into dist/ and check them
	rm -rf dist
	$(PYTHON) -m build
	twine check --strict dist/*

clean: ## Remove build output, caches and coverage data
	rm -rf build dist site htmlcov coverage.xml .coverage .coverage.* \
		.pytest_cache .mypy_cache .ruff_cache .hypothesis
	find . -type d -name __pycache__ -not -path "./.venv/*" -prune -exec rm -rf {} +

# Pass-through to the containerized environment: make env-test ENV=test
env-%:
	$(MAKE) -C environment $* ENV=$(or $(ENV),dev)
