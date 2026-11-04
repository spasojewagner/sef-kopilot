"""Shared fixtures for the API test suite.

Tests that need PostgreSQL run on the server named by ``SEF_TEST_DATABASE_URL`` (taken from the
environment or the repository's ``.env``), for example the one ``make up`` starts. The suite
creates a database of its own there, migrates it and drops it at the end, and every test runs in
a transaction that is rolled back. Without the variable those tests are skipped; CI sets it.
"""

from __future__ import annotations

import asyncio
import secrets
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

from sef_api.main import create_app
from sef_api.migrations import alembic_config
from sef_api.settings import Settings

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

#: A database URL nothing listens on: the application starts, its database checks fail.
UNREACHABLE_DATABASE = "postgresql+asyncpg://sef:sef@127.0.0.1:1/sef_kopilot"


class _TestServer(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPOSITORY_ROOT / ".env", extra="ignore")

    sef_test_database_url: str | None = None


TEST_SERVER_URL = _TestServer().sef_test_database_url


def settings_for(database_url: str = UNREACHABLE_DATABASE) -> Settings:
    """Settings for a test application, independent of the environment and of ``.env``."""
    return Settings.model_validate({"SEF_ENVIRONMENT": "test", "DATABASE_URL": database_url})


async def _execute(server: URL, statement: str) -> None:
    engine = create_async_engine(server, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        async with engine.connect() as connection:
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
