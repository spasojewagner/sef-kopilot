"""Cross-origin requests: the pages of the web application's configured origins may call the
API from a browser, and the pages of no other origin may."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from httpx import ASGITransport, AsyncClient

from sef_api.main import CORS_MAX_AGE_SECONDS, create_app

from .conftest import settings_for

WEB = "http://localhost:3000"
ELSEWHERE = "https://phishing.example"


@asynccontextmanager
async def serving(**variables: str) -> AsyncIterator[AsyncClient]:
    app = create_app(settings_for(**variables))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    await app.state.database.engine.dispose()


def preflight(origin: str, method: str = "POST") -> dict[str, str]:
    return {
        "Origin": origin,
        "Access-Control-Request-Method": method,
        "Access-Control-Request-Headers": "authorization, content-type",
    }


async def test_a_page_of_the_web_origin_is_told_what_it_may_send() -> None:
    async with serving(SEF_WEB_ORIGINS=WEB) as api:
        answer = await api.options("/invoices/validate", headers=preflight(WEB))

    assert answer.status_code == 200
    assert answer.headers["Access-Control-Allow-Origin"] == WEB
    assert set(answer.headers["Access-Control-Allow-Methods"].split(", ")) == {
        "GET",
        "POST",
        "PATCH",
        "DELETE",
    }
    allowed = {
        name.strip().lower() for name in answer.headers["Access-Control-Allow-Headers"].split(",")
    }
    assert {"authorization", "content-type", "last-event-id"} <= allowed
    assert answer.headers["Access-Control-Max-Age"] == str(CORS_MAX_AGE_SECONDS)
    assert "Access-Control-Allow-Credentials" not in answer.headers


async def test_a_page_of_the_web_origin_may_read_the_answer_and_its_headers() -> None:
    async with serving(SEF_WEB_ORIGINS=f"{WEB},https://sef-kopilot.pages.dev") as api:
        answer = await api.get("/health", headers={"Origin": "https://sef-kopilot.pages.dev"})

    assert answer.status_code == 200
    assert answer.headers["Access-Control-Allow-Origin"] == "https://sef-kopilot.pages.dev"
    exposed = {name.strip() for name in answer.headers["Access-Control-Expose-Headers"].split(",")}
    assert exposed == {"Location", "Retry-After"}
    assert answer.headers["Vary"] == "Origin"


async def test_a_page_may_read_an_error_too() -> None:
    """A body too long is refused before the application sees it, and the page that sent it
    can still read why."""
    async with serving(SEF_WEB_ORIGINS=WEB, SEF_MAX_BODY_BYTES="65536") as api:
        answer = await api.post(
            "/auth/login",
            content=b"{" + b" " * 70_000 + b"}",
            headers={"Origin": WEB, "Content-Type": "application/json"},
        )

    assert answer.status_code == 413
    assert answer.headers["Access-Control-Allow-Origin"] == WEB


async def test_a_page_of_another_origin_is_told_nothing() -> None:
    async with serving(SEF_WEB_ORIGINS=WEB) as api:
        asked = await api.options("/invoices/validate", headers=preflight(ELSEWHERE))
        read = await api.get("/health", headers={"Origin": ELSEWHERE})

    assert asked.status_code == 400
    assert "Access-Control-Allow-Origin" not in asked.headers
    assert read.status_code == 200  # the browser, not the API, keeps the page from reading it
    assert "Access-Control-Allow-Origin" not in read.headers


async def test_without_web_origins_no_page_of_another_origin_may_call() -> None:
    async with serving() as api:
        asked = await api.options("/invoices/validate", headers=preflight(WEB))
        read = await api.get("/health", headers={"Origin": WEB})

    assert asked.status_code == 405  # no preflight is answered: the route has no OPTIONS
    assert "Access-Control-Allow-Origin" not in asked.headers
    assert "Access-Control-Allow-Origin" not in read.headers
