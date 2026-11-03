# API documentation

The HTTP API documents itself: run the API (`make api`) and open <http://127.0.0.1:8000/docs>
(Swagger UI) or <http://127.0.0.1:8000/redoc>. The OpenAPI document is the contract; every
endpoint declares a summary, a description, response models and (from M2) authentication
requirements, and the test suite asserts that they are present.

This directory will hold what the generated documentation cannot express:

- authentication and multi-tenancy model (M2)
- job lifecycle and the SSE event stream (M2)
- the explanation and citation contract (M2)
- the patch model and approval flow (M3)
- MCP tools, scopes and the OAuth 2.1 flow (M4)
- SEF demo integration and error mapping (M5)
