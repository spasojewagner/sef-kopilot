"""The database dependency and the command-line migration configuration."""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Annotated

import pytest
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Text, literal, select, text
from sqlalchemy import cast as sql_cast
from sqlalchemy.exc import StatementError
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.db import Vector, get_session
from sef_api.main import create_app

from .conftest import REPOSITORY_ROOT, settings_for


async def test_a_request_gets_a_session_on_the_application_database(database_url: str) -> None:
    app = create_app(settings_for(database_url))

    @app.get("/probe")
    async def probe(session: Annotated[AsyncSession, Depends(get_session)]) -> str:
        return str(await session.scalar(text("SELECT current_database()")))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/probe")
    await app.state.database.engine.dispose()

    assert response.json() == database_url.rsplit("/", 1)[1]


def test_the_alembic_ini_runs_the_migrations_from_the_command_line() -> None:
    """``alembic -c apps/api/alembic.ini`` works from the repository root, here offline."""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "apps/api/alembic.ini", "upgrade", "head", "--sql"],
        cwd=REPOSITORY_ROOT,
        env=os.environ | {"DATABASE_URL": "postgresql+asyncpg://reviewer@localhost/sef"},
        capture_output=True,
        text=True,
        check=True,
    )

    assert "CREATE TABLE memberships" in result.stdout
    assert "Running upgrade  -> 0001" in result.stderr


async def test_a_vector_goes_in_and_comes_back_as_pgvector_keeps_it(session: AsyncSession) -> None:
    stored = await session.scalar(select(sql_cast(literal([0.25, -1.5, 3.0], Vector(3)), Text)))
    returned = await session.scalar(select(literal([0.25, -1.5, 3.0], Vector(3))))

    assert stored == "[0.25,-1.5,3]"
    assert returned == [0.25, -1.5, 3.0]
    assert Vector(3).python_type is list


async def test_a_vector_of_another_size_is_refused_before_it_is_sent(
    session: AsyncSession,
) -> None:
    with pytest.raises(StatementError, match="a vector of 2 numbers, not 3"):
        await session.scalar(select(literal([1.0, 2.0], Vector(3))))
