"""The database dependency."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.db import get_session
from sef_api.main import create_app

from .conftest import settings_for


async def test_a_request_gets_a_session_on_the_application_database(database_url: str) -> None:
    app = create_app(settings_for(database_url))

    @app.get("/probe")
    async def probe(session: Annotated[AsyncSession, Depends(get_session)]) -> str:
        return str(await session.scalar(text("SELECT current_database()")))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/probe")
    await app.state.database.engine.dispose()

    assert response.json() == database_url.rsplit("/", 1)[1]
