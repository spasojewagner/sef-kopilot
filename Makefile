# SEF Kopilot — developer entry points.
#
# Every target is a thin wrapper over a plain command, so it can be run by hand on a machine
# without GNU make (for example Windows without Git Bash): copy the command from the recipe.

.DEFAULT_GOAL := help
SHELL := bash

UV   ?= uv

.PHONY: help setup sync lint format typecheck test test-core test-api api clean

help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

setup: sync ## Install everything a fresh clone needs (Python deps, git hooks)
	$(UV) run pre-commit install --install-hooks

sync: ## Install / update Python dependencies for every workspace package
	$(UV) sync --all-packages

lint: ## Lint Python with ruff (no changes)
	$(UV) run ruff check .
	$(UV) run ruff format --check .

format: ## Format and auto-fix Python with ruff
	$(UV) run ruff check --fix .
	$(UV) run ruff format .

typecheck: ## Static typing with mypy --strict
	$(UV) run mypy

test: test-core test-api ## Run every test suite

test-core: ## Tests for packages/einvoice_core with the coverage gate (>= 90 %)
	$(UV) run pytest packages/einvoice_core --cov=einvoice_core --cov-report=term-missing --cov-fail-under=90

test-api: ## Tests for apps/api with the coverage gate (>= 80 %)
	$(UV) run pytest apps/api --cov=sef_api --cov-report=term-missing --cov-fail-under=80

api: ## Run the API locally with auto-reload (http://127.0.0.1:8000/docs)
	$(UV) run uvicorn sef_api.main:app --reload

clean: ## Remove caches and build output (keeps dependencies)
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage coverage.xml htmlcov
	find . -name __pycache__ -type d -prune -not -path './node_modules/*' -exec rm -rf {} +
