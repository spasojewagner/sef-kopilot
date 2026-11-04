"""Application factory.

Run locally with ``uv run uvicorn sef_api.main:create_app --factory --reload`` from the
repository root (or ``make api``); the interactive OpenAPI documentation is served at ``/docs``.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from sef_api import __version__
from sef_api.api_keys import routes as api_keys
from sef_api.auth import routes as auth
from sef_api.auth.service import TokenSettings
from sef_api.db import Database
from sef_api.invoices import routes as invoices
from sef_api.invoices.validator import Admission, ProcessValidator, ThreadValidator, Validator
from sef_api.members import routes as members
from sef_api.routes import health
from sef_api.settings import Settings

logger = logging.getLogger(__name__)

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
        "name": "invoices",
        "description": "Invoices and credit notes: the deterministic validator's report on them.",
    },
    {
        "name": "members",
        "description": "The people of the caller's organization, their roles (owner, "
        "accountant, client) and the invitations to join it.",
    },
]


def _validator(settings: Settings) -> Validator:
    if settings.validator == "thread":
        return ThreadValidator(max_elements=settings.max_invoice_elements)
    return ProcessValidator(
        max_elements=settings.max_invoice_elements, seconds=settings.validation_seconds
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application with its settings, its database and every router.

    A factory (instead of a module-level singleton) lets tests build a fresh application with
    their own settings, and keeps importing the module free of side effects. The database
    engine connects on first use and is disposed of when the application shuts down.
    """
    settings = settings if settings is not None else Settings()
    database = Database.connect(settings.database_url.get_secret_value())

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        # Start the validator, which compiles every rule set, so that no request pays for it.
        # If it cannot run, the API still starts, and /ready reports it.
        validator: Validator = application.state.validator
        await validator.start()
        if validator.problem is not None:
            logger.warning("the validator cannot run: %s", validator.problem)
        yield
        await validator.stop()
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
    app.state.validator = _validator(settings)
    app.state.admission = Admission(settings.max_validations_in_flight)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(invoices.router)
    app.include_router(members.router)
    app.include_router(members.invitations_router)
    app.include_router(api_keys.router)
    return app
