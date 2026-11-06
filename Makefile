# SEF Kopilot — developer entry points.
#
# Every target is a thin wrapper over a plain command, so it can be run by hand on a machine
# without GNU make (for example Windows without Git Bash): copy the command from the recipe.

.DEFAULT_GOAL := help
SHELL := bash

UV      ?= uv
PNPM    ?= pnpm
COMPOSE ?= docker compose --project-directory . -f infra/docker-compose.yml

.PHONY: help setup sync lint format typecheck test test-core test-api test-web api worker web build-web rulesets rulesets-check fixtures openapi corpus corpus-check ingest migrate up down logs psql clean

help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

setup: sync ## Install everything a fresh clone needs (Python and Node deps, git hooks)
	$(PNPM) install --frozen-lockfile
	$(UV) run pre-commit install --install-hooks

sync: ## Install / update Python dependencies for every workspace package
	$(UV) sync --all-packages

lint: ## Lint everything without changing files (ruff, Prettier, ESLint)
	$(UV) run ruff check .
	$(UV) run ruff format --check .
	$(PNPM) format:check
	$(PNPM) lint

format: ## Format and auto-fix everything (ruff, Prettier)
	$(UV) run ruff check --fix .
	$(UV) run ruff format .
	$(PNPM) format

typecheck: ## Static typing: mypy --strict and tsc --noEmit
	$(UV) run mypy
	$(PNPM) typecheck

test: test-core test-api test-web ## Run every test suite

test-core: ## Tests for packages/einvoice_core with the coverage gate (>= 90 %)
	$(UV) run pytest packages/einvoice_core --cov=einvoice_core --cov-report=term-missing --cov-fail-under=90

# Coverage of the API is measured by path: Alembic runs env.py and the revisions as standalone
# modules, which a package name (--cov=sef_api) does not match. Database tests need
# SEF_TEST_DATABASE_URL and the worker tests SEF_TEST_REDIS_URL as well (see .env.example);
# without them they are skipped.
test-api: ## Tests for apps/api with the coverage gate (>= 80 %)
	$(UV) run pytest apps/api --cov=apps/api/src/sef_api --cov-report=term-missing --cov-fail-under=80

test-web: ## Vitest suite for apps/web
	$(PNPM) --filter @sef-kopilot/web test

api: ## Run the API locally with auto-reload (http://127.0.0.1:8000/docs)
	$(UV) run uvicorn sef_api.main:create_app --factory --reload

worker: ## Run a worker for the jobs on the Redis queue (with SEF_JOBS=arq and `make up`)
	$(UV) run python -m sef_api.jobs.worker

migrate: ## Apply the database migrations to DATABASE_URL (default: the database of `make up`)
	$(UV) run alembic -c apps/api/alembic.ini upgrade head

web: ## Run the web app locally (http://localhost:3000)
	$(PNPM) --filter @sef-kopilot/web dev

build-web: ## Production build of the web app
	$(PNPM) --filter @sef-kopilot/web build

rulesets: ## Fetch the pinned EN 16931 and Peppol BIS rule sets into third_party/
	$(UV) run python scripts/fetch_rulesets.py

rulesets-check: ## Verify that third_party/ holds the pinned rule-set versions (no network)
	$(UV) run python scripts/fetch_rulesets.py --check

fixtures: ## Regenerate the mutation fixtures and the verdicts on the fixture corpus (needs rulesets)
	$(UV) run python scripts/make_fixtures.py

openapi: ## Write docs/api/openapi.json from the API, then the web application's types from it
	$(UV) run python scripts/export_openapi.py
	$(PNPM) --filter @sef-kopilot/web api:types

corpus: ## Download the corpus's official sources that are missing, then rewrite corpus/ from them
	$(UV) run python scripts/build_corpus.py --fetch

corpus-check: ## Fail if corpus/ is not what its downloaded sources make (no network)
	$(UV) run python scripts/build_corpus.py --check

ingest: ## Load corpus/ into DATABASE_URL, embedding it if EMBEDDINGS_PROVIDER names a provider
	$(UV) run python -m sef_api.rag.ingest

up: ## Start PostgreSQL (pgvector) and Redis in Docker and wait until they are healthy
	$(COMPOSE) up -d --wait

down: ## Stop the local infrastructure (keeps the database volume)
	$(COMPOSE) down

logs: ## Follow the infrastructure logs
	$(COMPOSE) logs -f

psql: ## Open a psql shell inside the database container
	$(COMPOSE) exec db psql -U $${POSTGRES_USER:-sef} -d $${POSTGRES_DB:-sef_kopilot}

clean: ## Remove caches and build output (keeps dependencies)
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage coverage.xml htmlcov apps/web/.next
	find . -name __pycache__ -type d -prune -not -path './node_modules/*' -exec rm -rf {} +
