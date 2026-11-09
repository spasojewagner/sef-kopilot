"""Cross-origin requests: the pages of the web application's configured origins may call the
API from a browser, and the pages of no other origin may, but for the authorization server's
public endpoints, which any page may call, as an MCP client in a browser does."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from httpx import ASGITransport, AsyncClient

from sef_api.cors import CORS_MAX_AGE_SECONDS, CORS_METHODS
from sef_api.main import create_app

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
        "PUT",
        "PATCH",
        "DELETE",
    }
    allowed = {
        name.strip().lower() for name in answer.headers["Access-Control-Allow-Headers"].split(",")
    }
    assert {"authorization", "content-type", "last-event-id"} <= allowed
    assert answer.headers["Access-Control-Max-Age"] == str(CORS_MAX_AGE_SECONDS)
    assert "Access-Control-Allow-Credentials" not in answer.headers


def test_a_page_may_send_every_method_the_routes_answer() -> None:
    """A method the routes answer and a page may not send is a route the web application cannot
    call: setting the organization's key to SEF with PUT was one."""
    paths = create_app(settings_for()).openapi()["paths"]
    answered = {method.upper() for operations in paths.values() for method in operations}

    assert "PUT" in answered
    assert answered <= set(CORS_METHODS)


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


#: An MCP client that runs in a browser, at an origin of its own.
INSPECTOR = "http://localhost:6274"
#: An API with an authorization server, and a web application.
SERVER = {"SEF_WEB_ORIGINS": WEB, "SEF_PUBLIC_URL": "https://api.example", "SEF_WEB_URL": WEB}


async def test_any_page_may_ask_the_authorization_servers_public_endpoints() -> None:
    async with serving(**SERVER) as api:
        token = await api.options(
            "/oauth/token",
            headers={
                "Origin": INSPECTOR,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        documents = [
            await api.options(
                path,
                headers={
                    "Origin": INSPECTOR,
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "mcp-protocol-version",
                },
            )
            for path in (
                "/.well-known/oauth-protected-resource/mcp",
                "/.well-known/oauth-protected-resource",
                "/.well-known/oauth-authorization-server",
            )
        ]
        register = await api.options(
            "/oauth/register",
            headers={
                "Origin": INSPECTOR,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        read = await api.get(
            "/.well-known/oauth-authorization-server", headers={"Origin": INSPECTOR}
        )

    for answer in [token, register, *documents]:
        assert answer.status_code == 200
        assert answer.headers["Access-Control-Allow-Origin"] == "*"
        assert "Access-Control-Allow-Credentials" not in answer.headers
    assert "POST" in token.headers["Access-Control-Allow-Methods"]
    assert "content-type" in token.headers["Access-Control-Allow-Headers"].lower()
    assert "mcp-protocol-version" in documents[0].headers["Access-Control-Allow-Headers"].lower()
    assert read.status_code == 200
    assert read.headers["Access-Control-Allow-Origin"] == "*"


async def test_the_rest_of_the_api_stays_the_web_applications() -> None:
    """A consent is the web application's to ask for, and an invoice its to send: a page of
    another origin is told nothing of them, as before."""
    async with serving(**SERVER) as api:
        consent = await api.options("/oauth/requests/r-1/approval", headers=preflight(INSPECTOR))
        validate = await api.options("/invoices/validate", headers=preflight(INSPECTOR))
        from_the_web = await api.options("/oauth/token", headers=preflight(WEB, "POST"))

    assert (consent.status_code, validate.status_code) == (400, 400)
    assert "Access-Control-Allow-Origin" not in consent.headers
    # The web application's pages may call the token endpoint too, as any page may.
    assert from_the_web.headers["Access-Control-Allow-Origin"] == "*"


async def test_without_an_authorization_server_no_endpoint_is_open_to_all() -> None:
    async with serving(SEF_WEB_ORIGINS=WEB) as api:
        answer = await api.options(
            "/oauth/token",
            headers={"Origin": INSPECTOR, "Access-Control-Request-Method": "POST"},
        )

    assert answer.status_code == 400
    assert "Access-Control-Allow-Origin" not in answer.headers
