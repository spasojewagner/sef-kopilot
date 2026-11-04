"""The PostgreSQL database: the declarative base, the engine, sessions and their dependency.

The engine is created with the application and connects lazily, on the first query; the
application's lifespan disposes of it on shutdown. Each request that needs the database gets
its own :class:`~sqlalchemy.ext.asyncio.AsyncSession` from :func:`get_session`; writes commit
explicitly where the service decides the unit of work is complete.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Final, cast

from fastapi import Depends, Request
from sqlalchemy import DateTime, MetaData, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

#: Constraint names are deterministic, so migrations can refer to them on every database.
NAMING_CONVENTION: Final = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

#: How long the readiness probe waits for the database.
PING_TIMEOUT_SECONDS: Final = 2.0


class Base(DeclarativeBase):
    """Base class of every ORM model; timestamps are always timezone-aware."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {datetime: DateTime(timezone=True)}  # noqa: RUF012


@dataclass(frozen=True)
class Database:
    """An engine and the session factory bound to it."""

    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]

    @classmethod
    def connect(cls, url: str, *, pooled: bool = True) -> Database:
        """Create the engine for ``url``; nothing connects until the first query.

        ``pool_pre_ping`` tests a pooled connection before handing it out, because managed
        PostgreSQL (Neon) closes idle connections. Without a pool (``pooled=False``) every
        session opens its own connection, which suits short-lived processes and tests.
        """
        engine = (
            create_async_engine(url, pool_pre_ping=True)
            if pooled
            else create_async_engine(url, poolclass=NullPool)
        )
        return cls(engine, async_sessionmaker(engine, expire_on_commit=False))

    async def ping(self, timeout: float = PING_TIMEOUT_SECONDS) -> bool:
        """True when the database answers a trivial query within ``timeout`` seconds."""
        try:
            async with asyncio.timeout(timeout), self.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except Exception:  # any failure means "not ready", never an error response
            return False
        return True


def get_database(request: Request) -> Database:
    """The application's database (a FastAPI dependency)."""
    return cast(Database, request.app.state.database)


async def get_session(
    database: Annotated[Database, Depends(get_database)],
) -> AsyncIterator[AsyncSession]:
    """One session per request (a FastAPI dependency); closed when the request ends."""
    async with database.sessions() as session:
        yield session
