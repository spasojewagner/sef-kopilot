"""Application factory.

Run locally with ``uv run uvicorn sef_api.main:create_app --factory --reload`` from the
repository root (or ``make api``); the interactive OpenAPI documentation is served at ``/docs``.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Final, cast

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import SecretStr

from sef_api import __version__
from sef_api.api_keys import routes as api_keys
from sef_api.auth import routes as auth
from sef_api.auth.service import TokenSettings
from sef_api.bodies import LimitBodies
from sef_api.charset import DeclareUTF8
from sef_api.db import Database
from sef_api.invoices import routes as invoices
from sef_api.invoices.validator import Admission, Validator, validator_for
from sef_api.jobs import routes as jobs
from sef_api.jobs import store as job_store
from sef_api.jobs.kinds import HANDLERS
from sef_api.jobs.queue import ArqRunner, redis_settings
from sef_api.jobs.runners import InlineRunner, JobRunner
from sef_api.jobs.runs import JobContext, run_job
from sef_api.llm import llm_for
from sef_api.members import routes as members
from sef_api.rag.embeddings import Embedder, embedder_for
from sef_api.rag.explainer import Explainer
from sef_api.rate_limits import RateLimiter, limits
from sef_api.repairs import routes as repairs
from sef_api.repairs.repairer import Repairer
from sef_api.routes import health
from sef_api.settings import Settings
from sef_api.unexpected import AnswerUnexpectedErrors

logger = logging.getLogger(__name__)

#: What a page of the web application's origin may send (CORS): the methods the API answers, the
#: headers its requests carry (the token, the body's type, where an event stream stopped), and
#: the headers of an answer it may read (where a new resource is, how long to wait). No
#: credentials: a page sends its token in a header, never in a cookie.
CORS_METHODS: Final = ("GET", "POST", "PATCH", "DELETE")
CORS_REQUEST_HEADERS: Final = ("Authorization", "Content-Type", "Last-Event-ID")
CORS_RESPONSE_HEADERS: Final = ("Location", "Retry-After")
#: How long a browser may keep the answer to a preflight: ten minutes.
CORS_MAX_AGE_SECONDS: Final = 600

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
        "description": "Invoices and credit notes: the deterministic validator's report on them, "
        "and explanations of its rules that cite the official documents.",
    },
    {
        "name": "repairs",
        "description": "Repairs of stored invoices: patches, written by the caller or by the "
        "language model, applied to a copy of an invoice and kept with what they did to it until "
        "a person decides.",
    },
    {
        "name": "jobs",
        "description": "Work done in the background for the caller's organization, such as "
        "validating its invoices again, and how far it has come.",
    },
    {
        "name": "members",
        "description": "The people of the caller's organization, their roles (owner, "
        "accountant, client) and the invitations to join it.",
    },
]


def _runner(app: FastAPI, settings: Settings) -> JobRunner:
    """Jobs go on the Redis queue of the workers, or run in the application's own event loop,
    each with the database, the validator and the settings the application has when it runs."""
    if settings.jobs == "arq":
        url = cast(SecretStr, settings.redis_url)  # the settings require it with arq
        return ArqRunner(redis_settings(url.get_secret_value()))

    async def run(job_id: uuid.UUID) -> None:
        context = JobContext(app.state.database, app.state.validator, app.state.settings)
        await run_job(context, job_id, HANDLERS)

    return InlineRunner(run)


def _model_users(settings: Settings) -> tuple[Explainer | None, Repairer | None]:
    """The explainer and the repairer, sharing the language model the settings name, or
    neither without one. The explainer closes the model when the application stops."""
    llm = llm_for(settings)
    if llm is None:
        return None, None
    return Explainer(llm), Repairer(llm)


async def _resume(app: FastAPI) -> None:
    """Have the jobs that the process before this one left unfinished run again. Without its
    database the application still starts, as /ready tells, and they wait for the next start."""
    try:
        async with app.state.database.sessions() as session:
            waiting = await job_store.unfinished(session)
    except Exception as error:
        logger.warning("the unfinished jobs were not resumed: %s", type(error).__name__)
        return
    runner: JobRunner = app.state.jobs
    for job_id in waiting:
        await runner.enqueue(job_id)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application with its settings, its database and every router.

    A factory (instead of a module-level singleton) lets tests build a fresh application with
    their own settings, and keeps importing the module free of side effects. The database
    engine connects on first use and is disposed of when the application shuts down. Jobs that
    run inline and were left unfinished are run again when it starts, and those running when it
    stops stay unfinished; the workers' sweep looks after the jobs on the Redis queue.
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
        if settings.jobs == "inline":
            await _resume(application)
        yield
        await application.state.jobs.stop()
        await validator.stop()
        explainer: Explainer | None = application.state.explainer
        if explainer is not None:
            await explainer.aclose()
        embedder: Embedder | None = application.state.embedder
        if embedder is not None:
            await embedder.aclose()
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
    # Innermost: an unexpected failure is answered inside the middlewares added after it, so
    # that its 500 is JSON in UTF-8 and carries the CORS headers a page needs to read it.
    app.add_middleware(AnswerUnexpectedErrors)
    app.add_middleware(LimitBodies, limit=settings.max_body_bytes)
    app.add_middleware(DeclareUTF8)  # it declares the charset of a 413 too
    if settings.web_origins:
        # Outermost: a preflight is answered before anything else runs, and every answer, an
        # error included, carries the headers a page needs to read it.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.web_origins),
            allow_methods=list(CORS_METHODS),
            allow_headers=list(CORS_REQUEST_HEADERS),
            expose_headers=list(CORS_RESPONSE_HEADERS),
            max_age=CORS_MAX_AGE_SECONDS,
        )
    app.state.settings = settings
    app.state.database = database
    app.state.tokens = TokenSettings.from_settings(settings)
    app.state.validator = validator_for(settings)
    app.state.admission = Admission(settings.max_validations_in_flight)
    app.state.limiter = RateLimiter()
    app.state.limits = limits(settings)
    app.state.jobs = _runner(app, settings)
    app.state.explainer, app.state.repairer = _model_users(settings)
    app.state.embedder = embedder_for(settings)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(invoices.router)
    app.include_router(repairs.router)
    app.add_exception_handler(repairs.ConflictError, repairs.answer_conflict)
    app.include_router(jobs.router)
    app.include_router(members.router)
    app.include_router(members.invitations_router)
    app.include_router(api_keys.router)
    return app
