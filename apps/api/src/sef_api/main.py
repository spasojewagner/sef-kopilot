"""Application factory.

Run locally with ``uv run uvicorn sef_api.main:create_app --factory --reload`` from the
repository root (or ``make api``); the interactive OpenAPI documentation is served at ``/docs``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from sef_api import __version__
from sef_api.auth import routes as auth
from sef_api.auth.service import TokenSettings
from sef_api.db import Database
from sef_api.members import routes as members
from sef_api.routes import health
from sef_api.settings import Settings

DESCRIPTION = """
Deterministic validation, plain-language explanations and reviewable repairs for Serbian (SEF)
and EU electronic invoices.

**This service is not a certified validator and is not affiliated with the Serbian Ministry of
Finance or the SEF platform.** By default it only ever talks to the public SEF *demo* environment.
"""

OPENAPI_TAGS = [
    {"name": "health", "description": "Liveness and readiness probes for orchestrators."},
    {
        "name": "auth",
        "description": "Accounts, sign-in and tokens: a short-lived access token for requests "
        "and a refresh token that is spent on use.",
    },
    {
        "name": "members",
        "description": "The people of the caller's organization and their roles: owner, "
        "accountant, client.",
    },
]


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application with its settings, its database and every router.

    A factory (instead of a module-level singleton) lets tests build a fresh application with
    their own settings, and keeps importing the module free of side effects. The database
    engine connects on first use and is disposed of when the application shuts down.
    """
    settings = settings if settings is not None else Settings()
    database = Database.connect(settings.database_url.get_secret_value())

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        await database.engine.dispose()

    app = FastAPI(
        title="SEF Kopilot API",
        version=__version__,
        description=DESCRIPTION,
        openapi_tags=OPENAPI_TAGS,
        license_info={
            "name": "Apache-2.0",
            "identifier": "Apache-2.0",
        },
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.database = database
    app.state.tokens = TokenSettings.from_settings(settings)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(members.router)
    return app
