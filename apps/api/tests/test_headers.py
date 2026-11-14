"""Every answer tells the browser to run nothing in it; the interactive documentation is
development's."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient

from sef_api.main import create_app

from .conftest import settings_for

POLICY = "default-src 'none'; frame-ancestors 'none'"
WEB = "https://app.example"


@asynccontextmanager
async def serving(**variables: str) -> AsyncIterator[AsyncClient]:
    app = create_app(settings_for(**variables))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    await app.state.database.engine.dispose()


async def test_every_answer_carries_the_headers_an_error_and_a_preflight_included() -> None:
    async with serving(SEF_WEB_ORIGINS=WEB) as api:
        answers = [
            await api.get("/health"),
            await api.get("/openapi.json"),
            await api.get("/invoices"),  # no token
            await api.get("/no/such/path"),
            await api.options(
                "/invoices",
                headers={"Origin": WEB, "Access-Control-Request-Method": "GET"},
            ),
        ]

    assert [answer.status_code for answer in answers] == [200, 200, 401, 404, 200]
    for answer in answers:
        assert answer.headers["content-security-policy"] == POLICY
        assert answer.headers["x-content-type-options"] == "nosniff"
        assert answer.headers["referrer-policy"] == "no-referrer"


async def test_the_documentation_is_served_outside_production_without_the_policy() -> None:
    async with serving() as api:
        pages = [await api.get("/docs"), await api.get("/redoc")]

    assert [page.status_code for page in pages] == [200, 200]
    for page in pages:
        assert "content-security-policy" not in page.headers
        assert page.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("page", ["/docs", "/redoc"])
async def test_production_serves_the_schema_but_no_documentation(page: str) -> None:
    async with serving(
        SEF_ENVIRONMENT="production", SEF_WEB_ORIGINS=WEB, SEF_PUBLIC_URL="https://api.example"
    ) as api:
        documentation = await api.get(page)
        schema = await api.get("/openapi.json")

    assert documentation.status_code == 404
    assert documentation.headers["content-security-policy"] == POLICY
    assert schema.status_code == 200
