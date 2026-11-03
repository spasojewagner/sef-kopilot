# sef-kopilot-api

FastAPI application exposing the validator, the explanation and repair layers, multi-tenant
persistence, background jobs with SSE progress, the SEF demo integration and (from M4) the MCP
server. The deterministic engine lives in `packages/einvoice_core`; this app only orchestrates it.

## Run locally

From the repository root:

```bash
uv sync --all-packages
uv run uvicorn sef_api.main:app --reload
```

- Interactive documentation: <http://127.0.0.1:8000/docs>
- Liveness: `GET /health` · Readiness: `GET /ready`

## Test

```bash
uv run pytest apps/api --cov=sef_api
```

## Layout

```text
src/sef_api/
  main.py        application factory (`create_app`) and the `app` instance for uvicorn
  routes/        one router module per resource
tests/           httpx-based tests against the ASGI app (no network)
```
