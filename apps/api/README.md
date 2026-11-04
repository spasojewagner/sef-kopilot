# sef-kopilot-api

FastAPI application exposing the validator, the explanation and repair layers, multi-tenant
persistence, background jobs with SSE progress, the SEF demo integration and (from M4) the MCP
server. The deterministic engine lives in `packages/einvoice_core`; this app only orchestrates it.

## Run locally

From the repository root, with PostgreSQL running (`make up` starts it in Docker):

```bash
uv sync --all-packages
make api              # uv run uvicorn sef_api.main:create_app --factory --reload
```

- Interactive documentation: <http://127.0.0.1:8000/docs>
- Liveness: `GET /health` · Readiness: `GET /ready` (503 while the database does not answer)

Configuration comes from the environment or a `.env` file in the working directory; the
variables are in [`.env.example`](../../.env.example). Without `DATABASE_URL` the API uses the
database of `make up`; in production the variable is required.

## Test

```bash
uv run pytest apps/api --cov=sef_api      # or: make test-api
```

Database tests run on the server named by `SEF_TEST_DATABASE_URL` (environment or `.env`), for
example `postgresql+asyncpg://sef:sef@localhost:5432/postgres` with `make up`. The suite creates
a database of its own, rolls every test back and drops the database at the end.
Without the variable those tests are skipped; CI always runs them.

## Layout

```text
src/sef_api/
  main.py        application factory (`create_app`): settings, database, routers
  settings.py    configuration from the environment (pydantic-settings)
  db.py          declarative base, engine, sessions, the `get_session` dependency
  routes/        one router module per resource
tests/           httpx-based tests against the ASGI app; database tests on PostgreSQL
```
