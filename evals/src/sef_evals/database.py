"""The database the explanations are measured on: the corpus, on a database of its own.

It is ``sef_evals`` on the PostgreSQL server the API's tests use (``SEF_TEST_DATABASE_URL``,
from the environment or the repository's ``.env``), dropped, made anew, migrated and given the
repository's corpus at every run, without embeddings: the passages retrieval finds then depend
on the code and the corpus alone. Nothing else is read from the environment, so that a
developer's ``DATABASE_URL`` is never touched.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Final

from alembic import command
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from sef_api.db import Database
from sef_api.migrations import alembic_config
from sef_api.rag.corpus import load_corpus
from sef_api.rag.ingest import ingest

__all__ = ["DATABASE", "DatabaseError", "corpus_database", "server_url"]

#: The database the runner makes anew on the tests' server.
DATABASE: Final = "sef_evals"


class DatabaseError(Exception):
    """No database to measure the explanations on; the message says what to do."""


def server_url(env_file: Path) -> str:
    """The URL of the tests' PostgreSQL server, ``SEF_TEST_DATABASE_URL`` from the environment
    or ``env_file``, as the API's tests read it."""

    class Server(BaseSettings):
        model_config = SettingsConfigDict(env_file=env_file, extra="ignore")

        sef_test_database_url: SecretStr | None = None

    url = Server().sef_test_database_url
    if url is None:
        raise DatabaseError(
            "SEF_TEST_DATABASE_URL is not set: name the PostgreSQL server the explanations are "
            "measured on, as .env.example does (`make up` starts one)"
        )
    return url.get_secret_value()


async def _execute(server: str, *statements: str) -> None:
    engine = create_async_engine(server, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        try:
            connection = await engine.connect()
        except (OSError, DBAPIError) as error:
            address = make_url(server)
            raise DatabaseError(
                f"the PostgreSQL server at {address.host}:{address.port or 5432} cannot be "
                f"reached ({type(error).__name__}): start it with `make up`, or `docker compose "
                "--project-directory . -f infra/docker-compose.yml up -d db`, and check "
                "SEF_TEST_DATABASE_URL"
            ) from None
        try:
            for statement in statements:
                await connection.execute(text(statement))
        finally:
            await connection.close()
    finally:
        await engine.dispose()


@asynccontextmanager
async def corpus_database(
    server: str, corpus: Path, name: str = DATABASE
) -> AsyncIterator[Database]:
    """The database ``name`` on ``server``, made anew, migrated and given the corpus at
    ``corpus``; dropped when the block ends."""
    drop = f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'
    await _execute(server, drop, f'CREATE DATABASE "{name}"')
    url = make_url(server).set(database=name).render_as_string(hide_password=False)
    database = Database.connect(url, pooled=False)
    try:
        # Alembic's environment runs its own event loop, so it migrates in a thread of its own.
        await asyncio.to_thread(command.upgrade, alembic_config(url), "head")
        await ingest(database, load_corpus(corpus))
        yield database
    finally:
        await database.engine.dispose()
        await _execute(server, drop)
