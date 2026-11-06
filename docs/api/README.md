# API documentation

The HTTP API documents itself: run the API (`make api`) and open <http://127.0.0.1:8000/docs>
(Swagger UI) or <http://127.0.0.1:8000/redoc>. The OpenAPI document is the contract; every
endpoint declares a summary, a description, response models and (from M2) authentication
requirements, and the test suite asserts that they are present.

[`openapi.json`](openapi.json) is that document as the API's code writes it, kept in the
repository so that a change to the contract shows in a diff. It is generated, never edited by
hand, and a test fails when it is out of date (`scripts/tests/test_export_openapi.py`). The web
application's types are generated from it (`apps/web/src/lib/api-schema.d.ts`), and its own
test fails when they are out of date. After changing the API:

```bash
make openapi    # uv run python scripts/export_openapi.py, then the web application's types
```

This directory will hold what the generated documentation cannot express:

- authentication and multi-tenancy model (M2)
- job lifecycle and the SSE event stream (M2)
- the explanation and citation contract (M2)
- the patch model and approval flow (M3)
- MCP tools, scopes and the OAuth 2.1 flow (M4)
- SEF demo integration and error mapping (M5)
