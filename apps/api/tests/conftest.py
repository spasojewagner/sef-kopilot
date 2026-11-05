"""Shared fixtures for the API test suite.

Tests that need PostgreSQL run on the server named by ``SEF_TEST_DATABASE_URL`` (taken from the
environment or the repository's ``.env``), for example the one ``make up`` starts. The suite
creates a database of its own there, migrates it and drops it at the end. Most tests run in a
transaction that is rolled back (``session``, ``api``); the tests about commits, locks,
concurrent requests and jobs use real sessions that commit (``committed_database``,
``committed_api``), and the tables are emptied after each of them. Without the variable the
database tests are skipped; CI sets it. The worker tests need Redis as well, the server named by
``SEF_TEST_REDIS_URL``, and are skipped without it.
"""

from __future__ import annotations

import asyncio
import secrets
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic import command
from httpx import ASGITransport, AsyncClient
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from sef_api.db import Database, get_session
from sef_api.main import create_app
from sef_api.migrations import alembic_config
from sef_api.rag.explainer import Explainer
from sef_api.settings import Settings

from .corpora import QuotingModel

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

#: A database URL nothing listens on: the application starts, its database checks fail.
UNREACHABLE_DATABASE = "postgresql+asyncpg://sef:sef@127.0.0.1:1/sef_kopilot"
#: Signs the test applications' access tokens; obviously not a key used anywhere else.
TEST_JWT_SECRET = "test" * 10


class _TestServer(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPOSITORY_ROOT / ".env", extra="ignore")

    sef_test_database_url: str | None = None
    sef_test_redis_url: str | None = None


TEST_SERVER_URL = _TestServer().sef_test_database_url
#: The Redis server of the worker tests, whose database they empty; without it they are skipped.
TEST_REDIS_URL = _TestServer().sef_test_redis_url


def settings_for(database_url: str = UNREACHABLE_DATABASE, **variables: str) -> Settings:
    """Settings for a test application, independent of the environment and of ``.env``;
    ``variables`` set or override environment variables (``SEF_MAX_INVOICE_BYTES="1024"``).

    Invoices are validated in a thread of the test's process: the child process of the API is
    tested on its own (``test_validator.py``)."""
    return Settings.model_validate(
        {
            "SEF_ENVIRONMENT": "test",
            "DATABASE_URL": database_url,
            "SEF_JWT_SECRET": TEST_JWT_SECRET,
            "SEF_VALIDATOR": "thread",
            **variables,
        }
    )


async def _execute(server: URL, *statements: str) -> None:
    engine = create_async_engine(server, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            for statement in statements:
                await connection.execute(text(statement))
    finally:
        await engine.dispose()


@contextmanager
def temporary_database() -> Iterator[str]:
    """A new, empty database on the test server, dropped afterwards."""
    if not TEST_SERVER_URL:
        pytest.skip("set SEF_TEST_DATABASE_URL to a PostgreSQL server to run database tests")
    server = make_url(TEST_SERVER_URL)
    name = f"sef_test_{secrets.token_hex(6)}"
    asyncio.run(_execute(server, f'CREATE DATABASE "{name}"'))
    try:
        yield server.set(database=name).render_as_string(hide_password=False)
    finally:
        asyncio.run(_execute(server, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """The suite's database, migrated to the latest revision."""
    with temporary_database() as url:
        command.upgrade(alembic_config(url), "head")
        yield url


@pytest.fixture
def empty_database_url() -> Iterator[str]:
    """A database for one test, without any migration applied."""
    with temporary_database() as url:
        yield url


@pytest.fixture
async def session(database_url: str) -> AsyncIterator[AsyncSession]:
    """A session on the suite's database whose work, commits included, is rolled back."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        ) as session:
            yield session
        await transaction.rollback()
    await engine.dispose()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """An HTTP client bound to a fresh application whose database cannot be reached.

    ``ASGITransport`` calls the ASGI app in-process, so tests exercise the real routing,
    validation and serialisation without opening a network socket.
    """
    app = create_app(settings_for())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    await app.state.database.engine.dispose()


class RecordingRunner:
    """A job runner that runs nothing and notes the jobs it is given: no worker could see them
    in a transaction that is rolled back."""

    def __init__(self) -> None:
        self.enqueued: list[uuid.UUID] = []

    async def enqueue(self, job_id: uuid.UUID) -> None:
        self.enqueued.append(job_id)

    async def stop(self) -> None:
        pass


@pytest.fixture
async def api(session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """A client of an application whose requests all use the test's rolled-back session, whose
    jobs are noted rather than run, and whose explanations a stand-in model writes."""
    app = create_app(settings_for())
    app.state.jobs = RecordingRunner()
    app.state.explainer = Explainer(QuotingModel())

    async def the_test_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = the_test_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    await app.state.database.engine.dispose()


@pytest.fixture
async def committed_database(database_url: str) -> AsyncIterator[Database]:
    """The suite's database with sessions as the application makes them: every commit is real.

    The tables are emptied afterwards, the corpus's too, so the next test starts from nothing.
    """
    database = Database.connect(database_url, pooled=False)
    try:
        yield database
    finally:
        await database.engine.dispose()
        await _execute(
            make_url(database_url),
            "SET lock_timeout = '10s'",  # a test that left a transaction open fails, not hangs
            "TRUNCATE organizations, users, corpus_documents CASCADE",
        )


@pytest.fixture
async def committed_api(
    committed_database: Database, database_url: str
) -> AsyncIterator[AsyncClient]:
    """A client of an application as in production: each request gets a session of its own
    and commits for real, so a change that is not committed is lost with the request."""
    app = create_app(settings_for(database_url))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    await app.state.database.engine.dispose()
