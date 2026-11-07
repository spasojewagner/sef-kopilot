"""The MCP server at ``/mcp`` (ADR-0042): whom it admits, and how it answers.

The endpoint opens database sessions of its own, as in production, so these tests run on the
suite's database with real commits (``committed_database``).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import update

from sef_api.auth.permissions import Permission
from sef_api.db import Database
from sef_api.main import create_app
from sef_api.models import ApiKey, User

from .conftest import settings_for
from .factories import Key, Office, api_key, office

#: The tools the server offers, what each requires, and arguments it accepts: the audit that a
#: tool cannot join the server without a permission of its own.
TOOLS: dict[str, tuple[Permission, dict[str, Any]]] = {}

#: The headers a client sends with every message it posts.
POSTED = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@dataclass(frozen=True)
class Served:
    """The application, running, and Primer's office with its client's key, which holds every
    permission a key may hold."""

    app: FastAPI
    primer: Office
    key: Key

    def http(self, headers: Mapping[str, str] | None = None) -> AsyncClient:
        """A plain HTTP client of the application, for what the transport answers."""
        return AsyncClient(
            transport=ASGITransport(app=self.app), base_url="http://test", headers=headers
        )


@asynccontextmanager
async def running(app: FastAPI) -> AsyncIterator[None]:
    """The application's lifespan, in a task of its own: the MCP endpoint's task group must be
    entered and left in one task, and a fixture's setup and teardown may run in two."""
    started, stopping = asyncio.Event(), asyncio.Event()

    async def lifespan() -> None:
        async with app.router.lifespan_context(app):
            started.set()
            await stopping.wait()

    task = asyncio.create_task(lifespan())
    waiting = asyncio.create_task(started.wait())
    await asyncio.wait({task, waiting}, return_when=asyncio.FIRST_COMPLETED)
    if task.done():
        waiting.cancel()
        task.result()  # the lifespan's failure
    try:
        yield
    finally:
        stopping.set()
        await task


@asynccontextmanager
async def serving(database: Database, database_url: str, **variables: str) -> AsyncIterator[Served]:
    async with database.sessions() as setup:
        primer = await office(setup, "Primer Računovodstvo", "primer.example")
        key = await api_key(setup, primer.organization, primer.client)
        await setup.commit()
    app = create_app(settings_for(database_url, **variables))
    async with running(app):
        yield Served(app, primer, key)


@pytest.fixture
async def served(committed_database: Database, database_url: str) -> AsyncIterator[Served]:
    async with serving(committed_database, database_url) as running_app:
        yield running_app


@asynccontextmanager
async def connected(app: FastAPI, key: Key) -> AsyncIterator[Client]:
    """A client of the SDK, connected to the application with ``key``."""
    http = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://test", headers=key.header()
    )
    async with http, Client(streamable_http_client("http://test/mcp", http_client=http)) as client:
        yield client


async def key_with(database: Database, served: Served, *permissions: Permission) -> Key:
    """Another key of Primer's client, holding ``permissions``."""
    async with database.sessions() as setup:
        key = await api_key(setup, served.primer.organization, served.primer.client, *permissions)
        await setup.commit()
    return key


def initialize(version: str = "2025-06-18") -> dict[str, Any]:
    """The message with which a client of the protocol's revision ``version`` begins."""
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": version,
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    }


def asking(method: str, **params: Any) -> dict[str, Any]:
    """A message that asks the server for ``method`` with ``params``."""
    return {"jsonrpc": "2.0", "id": 2, "method": method, "params": params}


# --- whom the endpoint admits ------------------------------------------------------------------


async def test_a_client_of_an_earlier_revision_is_answered_without_a_session(
    served: Served,
) -> None:
    async with served.http(served.key.header() | POSTED) as http:
        started = await http.post("/mcp", json=initialize("2025-06-18"))
        listed = await http.post(
            "/mcp", headers={"MCP-Protocol-Version": "2025-06-18"}, json=asking("tools/list")
        )

    assert started.status_code == listed.status_code == 200
    assert started.json()["result"]["protocolVersion"] == "2025-06-18"
    assert started.json()["result"]["serverInfo"]["name"] == "SEF Kopilot"
    assert "mcp-session-id" not in started.headers
    assert sorted(tool["name"] for tool in listed.json()["result"]["tools"]) == sorted(TOOLS)


async def test_a_client_of_the_current_revision_is_answered(served: Served) -> None:
    async with connected(served.app, served.key) as client:
        offered = (await client.list_tools()).tools

    assert sorted(tool.name for tool in offered) == sorted(TOOLS)


async def test_a_request_without_an_api_key_is_refused(served: Served) -> None:
    async with served.http(POSTED) as http:
        anonymous = await http.post("/mcp", json=initialize())
        signed_in = await http.post("/mcp", json=initialize(), headers=served.primer.as_client())
        unknown = await http.post(
            "/mcp", json=initialize(), headers={"Authorization": "Bearer sefk_unknown"}
        )

    assert (anonymous.status_code, anonymous.json()) == (401, {"detail": "not signed in"})
    assert anonymous.headers["WWW-Authenticate"] == "Bearer"
    # An access token is the web application's, issued for the API's routes.
    assert (signed_in.status_code, signed_in.json()) == (
        401,
        {"detail": "the MCP endpoint takes an API key"},
    )
    assert (unknown.status_code, unknown.json()) == (
        401,
        {"detail": "invalid, expired or revoked API key"},
    )
    assert signed_in.headers["WWW-Authenticate"] == unknown.headers["WWW-Authenticate"]
    assert unknown.headers["WWW-Authenticate"] == 'Bearer error="invalid_token"'


async def test_a_revoked_key_or_a_member_who_left_is_refused(
    served: Served, committed_database: Database
) -> None:
    revoked = await key_with(committed_database, served, Permission.INVOICES_VALIDATE)
    async with committed_database.sessions() as session:
        await session.execute(
            update(ApiKey).where(ApiKey.id == revoked.row.id).values(revoked_at=datetime.now(UTC))
        )
        await session.commit()
    async with served.http(POSTED) as http:
        with_revoked = await http.post("/mcp", json=initialize(), headers=revoked.header())
    async with committed_database.sessions() as session:
        await session.execute(
            update(User).where(User.id == served.primer.client.id).values(is_active=False)
        )
        await session.commit()
    async with served.http(POSTED) as http:
        after_leaving = await http.post("/mcp", json=initialize(), headers=served.key.header())

    assert (with_revoked.status_code, with_revoked.json()) == (
        401,
        {"detail": "invalid, expired or revoked API key"},
    )
    assert (after_leaving.status_code, after_leaving.json()) == (
        401,
        {"detail": "the account or its membership is no longer active"},
    )


@pytest.mark.parametrize("method", ["GET", "DELETE", "PUT"])
async def test_only_posts_are_answered(method: str, served: Served) -> None:
    # A GET would open a stream of the server's own messages, of which it has none.
    async with served.http(served.key.header()) as http:
        answered = await http.request(method, "/mcp", headers={"Accept": "text/event-stream"})

    assert (answered.status_code, answered.json()) == (405, {"detail": "Method Not Allowed"})
    assert answered.headers["Allow"] == "POST"


async def test_a_page_of_another_origin_is_refused(
    committed_database: Database, database_url: str
) -> None:
    async with (
        serving(committed_database, database_url, SEF_WEB_ORIGINS="https://app.example") as served,
        served.http(served.key.header() | POSTED) as http,
    ):
        foreign = await http.post(
            "/mcp", json=initialize(), headers={"Origin": "https://elsewhere.example"}
        )
        own = await http.post("/mcp", json=initialize(), headers={"Origin": "https://app.example"})
        without = await http.post("/mcp", json=initialize())

    assert (foreign.status_code, foreign.json()) == (
        403,
        {"detail": "requests from this origin are not accepted"},
    )
    assert own.status_code == without.status_code == 200


async def test_a_message_over_the_limit_on_bodies_is_refused(
    committed_database: Database, database_url: str
) -> None:
    padded = initialize() | {"padding": "x" * 70_000}
    async with (
        serving(committed_database, database_url, SEF_MAX_BODY_BYTES="65536") as served,
        served.http(served.key.header() | POSTED) as http,
    ):
        answered = await http.post("/mcp", json=padded)

    assert answered.status_code == 413


# --- the process -------------------------------------------------------------------------------


def test_making_the_application_leaves_the_root_logger_as_it_was(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = logging.getLogger()
    # As in production, where nothing has configured it: pytest's handlers would hide a change.
    monkeypatch.setattr(root, "handlers", [])
    monkeypatch.setattr(root, "level", logging.WARNING)

    create_app(settings_for())

    assert (root.handlers, root.level) == ([], logging.WARNING)
