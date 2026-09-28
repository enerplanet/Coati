# Development and test environment for Coati: one Docker image carrying Python,
# the dependencies of the tests, ruff, mypy, make, git and MkDocs.
#
#   make -C environment build   # build the image
#   make -C environment test    # run the test suite inside the container
#   make -C environment lint    # ruff and mypy inside the container
#   make -C environment check   # both, what CI runs
#   make -C environment docs    # serve the documentation on http://localhost:8000
#   make -C environment cli ARGS="inspect tests/data/example.nc"
#   make -C environment shell   # interactive shell in the image
#
# ENV=dev (default) or test selects .env.$(ENV).

ENV      ?= dev
ENV_FILE := .env.$(ENV)
# Prefer compose v2 (docker compose); fall back to the legacy v1 binary.
COMPOSE_BIN := $(shell docker compose version >/dev/null 2>&1 && echo "docker compose" || echo "docker-compose")
COMPOSE  := $(COMPOSE_BIN) --env-file $(ENV_FILE) -f docker-compose.yml

# The containers run as the user who runs make, so that what they write into
# the checkout belongs to that user.
export HOST_UID := $(shell id -u)
export HOST_GID := $(shell id -g)

.DEFAULT_GOAL := help
.PHONY: build test lint check docs cli shell clean help

build: ## Build the environment image (Python, test dependencies, ruff, mypy, MkDocs)
	$(COMPOSE) build test

test: ## Run the test suite inside the container (TEST_TARGET from the env file)
	$(COMPOSE) run --rm test

lint: ## Run ruff and mypy inside the container
	$(COMPOSE) run --rm lint

check: test lint ## Tests and lint, what CI runs

docs: ## Serve the documentation with live reload (DOCS_PORT from the env file)
	$(COMPOSE) up docs

cli: ## Run the coati command from the working tree: make cli ARGS="SOURCE OUTPUT FRAMEWORK"
	$(COMPOSE) run --rm coati $(ARGS)

shell: ## Interactive shell in the environment image
	$(COMPOSE) run --rm shell

clean: ## Remove this environment's containers and image
	$(COMPOSE) down --rmi local --volumes --remove-orphans

help: ## Show this help
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-8s\033[0m %s\n", $$1, $$2}'
