"""The PostgreSQL database: the declarative base, the engine, sessions and their dependency,
and pgvector's column type.

The engine is created with the application and connects lazily, on the first query; the
application's lifespan disposes of it on shutdown. Each request that needs the database gets
its own :class:`~sqlalchemy.ext.asyncio.AsyncSession` from :func:`get_session`; writes commit
explicitly where the service decides the unit of work is complete.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Final, cast

from fastapi import Depends, Request
from sqlalchemy import DateTime, Dialect, MetaData, Text, text
from sqlalchemy import cast as sql_cast
from sqlalchemy.dialects.postgresql import base as postgresql_types
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool
from sqlalchemy.sql.elements import BindParameter, ColumnElement
from sqlalchemy.types import UserDefinedType

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


class Vector(UserDefinedType[list[float]]):
    """pgvector's ``vector(n)``: a list of ``n`` floats.

    Values travel in pgvector's text form, ``[0.1,0.2]``, cast on the server, so asyncpg needs
    no codec of its own for the type.
    """

    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **kwargs: object) -> str:
        del kwargs
        return f"vector({self.dimensions})"

    def bind_processor(self, dialect: Dialect) -> Callable[[list[float] | None], str | None]:
        del dialect

        def process(value: list[float] | None) -> str | None:
            if value is None:
                return None
            if len(value) != self.dimensions:
                raise ValueError(f"a vector of {len(value)} numbers, not {self.dimensions}")
            return "[" + ",".join(repr(float(number)) for number in value) + "]"

        return process

    def bind_expression(self, bindvalue: BindParameter[list[float]]) -> ColumnElement[list[float]]:
        return sql_cast(sql_cast(bindvalue, Text), self)

    def result_processor(
        self, dialect: Dialect, coltype: object
    ) -> Callable[[str | None], list[float] | None]:
        del dialect, coltype

        def process(value: str | None) -> list[float] | None:
            if value is None:
                return None
            return [float(number) for number in value.strip("[]").split(",") if number]

        return process

    @property
    def python_type(self) -> type[list[float]]:
        return list


# The PostgreSQL dialect reflects a column of an unknown type as NullType, with a warning; it
# knows ``vector(n)`` from here on, so that Alembic compares the corpus's table with its model.
postgresql_types.ischema_names["vector"] = Vector


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
