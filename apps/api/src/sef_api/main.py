"""Application factory.

Run locally with ``uv run uvicorn sef_api.main:app --reload`` from the repository root; the
interactive OpenAPI documentation is served at ``/docs``.
"""

from fastapi import FastAPI

from sef_api import __version__
from sef_api.routes import health

DESCRIPTION = """
Deterministic validation, plain-language explanations and reviewable repairs for Serbian (SEF)
and EU electronic invoices.

**This service is not a certified validator and is not affiliated with the Serbian Ministry of
Finance or the SEF platform.** By default it only ever talks to the public SEF *demo* environment.
"""

OPENAPI_TAGS = [
    {"name": "health", "description": "Liveness and readiness probes for orchestrators."},
]


def create_app() -> FastAPI:
    """Build the FastAPI application with every router attached.

    A factory (instead of a module-level singleton) lets tests build a fresh application per
    test and lets deployments pass explicit settings once configuration exists.
    """
    app = FastAPI(
        title="SEF Kopilot API",
        version=__version__,
        description=DESCRIPTION,
        openapi_tags=OPENAPI_TAGS,
        license_info={
            "name": "Apache-2.0",
            "identifier": "Apache-2.0",
        },
    )
    app.include_router(health.router)
    return app


app = create_app()
