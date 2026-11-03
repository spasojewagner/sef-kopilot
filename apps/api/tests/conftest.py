"""Shared fixtures for the API test suite."""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from sef_api.main import create_app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """An HTTP client bound directly to a fresh application instance.

    ``ASGITransport`` calls the ASGI app in-process, so tests exercise the real routing,
    validation and serialisation without opening a network socket.
    """
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
