"""Alembic environment: migrations run against ``DATABASE_URL`` on an asyncpg engine.

A URL given in ``config.attributes["database_url"]`` (see :func:`sef_api.migrations.alembic_config`)
takes precedence, which is how the tests point migrations at their own databases.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from sef_api import models  # noqa: F401  (registers the tables on the metadata)
from sef_api.db import Base
from sef_api.settings import Settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def _url() -> str:
    url = config.attributes.get("database_url")
    return str(url) if url is not None else Settings().database_url.get_secret_value()


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def _run_online() -> None:
    engine = create_async_engine(_url(), poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    context.configure(
        url=_url(),
        target_metadata=Base.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(_run_online())
