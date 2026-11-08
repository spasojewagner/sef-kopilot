"""Application factory.

Run locally with ``uv run uvicorn sef_api.main:create_app --factory --reload`` from the
repository root (or ``make api``); the interactive OpenAPI documentation is served at ``/docs``.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from typing import Final, cast

import httpx
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from pydantic import SecretStr

from sef_api import __version__
from sef_api.api_keys import routes as api_keys
from sef_api.auth import routes as auth
from sef_api.auth.service import TokenSettings
from sef_api.bodies import LimitBodies
from sef_api.charset import DeclareUTF8
from sef_api.cors import Cors
from sef_api.db import Database
from sef_api.error_tracking import track_errors
from sef_api.invoices import routes as invoices
from sef_api.invoices.validator import Admission, Validator, validator_for
from sef_api.jobs import routes as jobs
from sef_api.jobs import store as job_store
from sef_api.jobs.kinds import HANDLERS
from sef_api.jobs.queue import ArqRunner, redis_settings
from sef_api.jobs.runners import InlineRunner, JobRunner
from sef_api.jobs.runs import JobContext, run_job
from sef_api.llm import llm_for
from sef_api.logs import RequestIds
from sef_api.mcp import server as mcp
from sef_api.members import routes as members
from sef_api.model_traces import ModelTraces, TracedClient
from sef_api.oauth import documents
from sef_api.oauth import metadata as oauth_metadata
from sef_api.oauth import routes as oauth
from sef_api.organization import routes as organization
from sef_api.rag.embeddings import Embedder, embedder_for
from sef_api.rag.explainer import Explainer
from sef_api.rate_limits import RateLimiter, limits
from sef_api.refusals import answer_refused
from sef_api.repairs import routes as repairs
from sef_api.repairs.repairer import Repairer
from sef_api.retention import keep_forgetting
from sef_api.routes import health
from sef_api.rules import routes as rules
from sef_api.sef import routes as sef
from sef_api.sef.client import SefClient
from sef_api.sef.keys import keyring_for
from sef_api.sef.submissions import NotSendableError
from sef_api.settings import Settings
from sef_api.unexpected import AnswerUnexpectedErrors

logger = logging.getLogger(__name__)

#: The authorization server's endpoints a page of any origin may call (``sef_api.cors``).
OAUTH_PUBLIC_PATHS: Final = frozenset(
    {
        oauth_metadata.METADATA_PATH,
        "/.well-known/oauth-protected-resource",
        "/.well-known/oauth-authorization-server",
        "/oauth/register",
        "/oauth/token",
    }
)

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
    {
        "name": "organization",
        "description": "The caller's organization: its name, how long it keeps its stored "
        "invoices before they are deleted, and its key to SEF.",
    },
    {
        "name": "sef",
        "description": "Stored invoices sent to SEF's demo environment in their "
        "organization's name, once the validator passes them, and what SEF answered.",
    },
    {
        "name": "oauth",
        "description": "The OAuth 2.1 authorization server of the MCP endpoint, once "
        "`SEF_PUBLIC_URL` names the API's address: the clients that register themselves.",
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
    """The explainer and the repairer, sharing the language model the settings name, traced
    where Langfuse's keys are set (ADR-0049), or neither without one. The explainer closes the
    model when the application stops."""
    llm = llm_for(settings)
    if llm is None:
        return None, None
    if settings.langfuse_public_key is not None and settings.langfuse_secret_key is not None:
        traces = ModelTraces(
            settings.langfuse_host,
            settings.langfuse_public_key,
            settings.langfuse_secret_key,
            environment=settings.environment,
        )
        llm = TracedClient(llm, traces)
    return Explainer(llm), Repairer(llm)


@asynccontextmanager
async def _deleting_old_data(database: Database, job_retention_days: int) -> AsyncIterator[None]:
    """Delete what is past its retention now, then every few hours, while the application runs:
    the old finished jobs (ADR-0038) and the invoices kept past their organization's period
    (ADR-0039)."""
    deleting = asyncio.create_task(keep_forgetting(database, job_retention_days))
    try:
        yield
    finally:
        deleting.cancel()
        with suppress(asyncio.CancelledError):
            await deleting


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
    """Build the FastAPI application with its settings, its database, every router and the
    MCP endpoint.

    A factory (instead of a module-level singleton) lets tests build a fresh application with
    their own settings, and keeps importing the module free of side effects. The database
    engine connects on first use and is disposed of when the application shuts down. Jobs that
    run inline and were left unfinished are run again when it starts, and those running when it
    stops stay unfinished; the workers' sweep looks after the jobs on the Redis queue.
    """
    settings = settings if settings is not None else Settings()
    track_errors(settings)
    database = Database.connect(settings.database_url.get_secret_value())

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        # Start the validator, which compiles every rule set, so that no request pays for it.
        # If it cannot run, the API still starts, and /ready reports it.
        validator: Validator = application.state.validator
        await validator.start()
        if validator.problem is not None:
            logger.warning("the validator cannot run: %s", validator.problem)
        async with AsyncExitStack() as running:
            if settings.jobs == "inline":
                await _resume(application)
                # The jobs run here, so here old data is deleted.
                await running.enter_async_context(
                    _deleting_old_data(database, settings.job_retention_days)
                )
            # The MCP endpoint's sessions, which it keeps only for a message's length.
            await running.enter_async_context(application.state.mcp.run())
            yield
        await application.state.jobs.stop()
        await validator.stop()
        explainer: Explainer | None = application.state.explainer
        if explainer is not None:
            await explainer.aclose()
        embedder: Embedder | None = application.state.embedder
        if embedder is not None:
            await embedder.aclose()
        await application.state.sef_http.aclose()
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
    # Outermost: a preflight is answered before anything else runs, and every answer, an error
    # included, carries the headers a page needs to read it. The authorization server's public
    # endpoints answer a page of any origin, once there is an authorization server.
    app.add_middleware(
        Cors,
        web_origins=settings.web_origins,
        public_paths=OAUTH_PUBLIC_PATHS if settings.public_url is not None else (),
    )
    # Around everything: every line logged while a request is answered names it.
    app.add_middleware(RequestIds)
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
    # Seals and opens the organizations' SEF keys, where SEF_FERNET_KEY is set (ADR-0050).
    app.state.sef_keys = keyring_for(settings)
    # Speaks to SEF for every organization, each request with that organization's key.
    app.state.sef_http = httpx.AsyncClient(timeout=SefClient.TIMEOUT_SECONDS)
    # Fetches a client's metadata document, where the operator allows it (ADR-0045).
    app.state.client_documents = documents.fetch if settings.client_metadata_documents else None
    for router in (
        health.router,
        auth.router,
        invoices.router,
        repairs.router,
        rules.router,
        jobs.router,
        members.router,
        members.invitations_router,
        organization.router,
        api_keys.router,
        sef.router,
        oauth.router,
        oauth_metadata.router,
    ):
        app.include_router(router)
    app.add_exception_handler(RequestValidationError, answer_refused)
    app.add_exception_handler(repairs.ConflictError, repairs.answer_conflict)
    app.add_exception_handler(NotSendableError, sef.answer_not_sendable)
    app.state.mcp = mcp.mount(app, settings)
    return app
