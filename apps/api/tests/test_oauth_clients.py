"""``POST /oauth/register``: an MCP client registers itself with the authorization server
(RFC 7591, ADR-0044), as a public client, with the redirect URIs OAuth 2.1 allows."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.models import OAuthClient

from .test_invoices_validate import application

#: The API's address, which makes it an authorization server.
PUBLIC = {"SEF_PUBLIC_URL": "https://api.example"}

#: What an assistant on the web sends, roughly.
ASSISTANT: dict[str, Any] = {
    "client_name": "An assistant",
    "redirect_uris": ["https://assistant.example/api/mcp/auth_callback"],
    "grant_types": ["authorization_code", "refresh_token"],
    "response_types": ["code"],
    "token_endpoint_auth_method": "client_secret_post",
    "scope": "invoices:validate",
}


@asynccontextmanager
async def server(session: AsyncSession, **variables: str) -> AsyncIterator[AsyncClient]:
    async with application(session, None, **(PUBLIC | variables)) as api:
        yield api


async def test_a_client_registers_as_a_public_client(session: AsyncSession) -> None:
    async with server(session) as api:
        response = await api.post("/oauth/register", json=ASSISTANT)

    assert response.status_code == 201
    assert response.headers["Cache-Control"] == "no-store"
    registered = response.json()
    # Whatever it asked for, it gets no secret, and is told so.
    assert "client_secret" not in registered
    assert registered["token_endpoint_auth_method"] == "none"
    assert registered["redirect_uris"] == ASSISTANT["redirect_uris"]
    assert registered["grant_types"] == ["authorization_code", "refresh_token"]
    assert registered["response_types"] == ["code"]
    assert registered["client_name"] == "An assistant"
    stored = await session.scalar(select(OAuthClient))
    assert stored is not None
    assert (stored.id, stored.redirect_uris, stored.grant_types) == (
        registered["client_id"],
        ASSISTANT["redirect_uris"],
        ["authorization_code", "refresh_token"],
    )
    assert registered["client_id_issued_at"] == int(stored.created_at.timestamp())


async def test_the_least_a_client_says_is_enough(session: AsyncSession) -> None:
    async with server(session) as api:
        response = await api.post(
            "/oauth/register", json={"redirect_uris": ["http://127.0.0.1:33418/callback"]}
        )

    assert response.status_code == 201
    registered = response.json()
    assert registered["client_name"] is None
    assert registered["grant_types"] == ["authorization_code"]
    assert len(registered["client_id"]) >= 32


@pytest.mark.parametrize(
    "uri",
    [
        "https://assistant.example/callback?from=mcp",
        "http://127.0.0.1:6274/oauth/callback",
        "http://localhost:33418/callback",
        "http://[::1]:8080/callback",
        "cursor://anysphere.cursor-retrieval/oauth/callback",
        "com.example.desktop:/oauth2redirect",
    ],
)
async def test_a_redirect_uri_oauth_allows_is_registered(session: AsyncSession, uri: str) -> None:
    async with server(session) as api:
        response = await api.post("/oauth/register", json={"redirect_uris": [uri]})

    assert response.status_code == 201
    assert response.json()["redirect_uris"] == [uri]


@pytest.mark.parametrize(
    ("uri", "why"),
    [
        ("http://assistant.example/callback", "uses http, which only the loopback interface may"),
        ("https://assistant.example/callback#done", "has a fragment"),
        ("/callback", "is not an absolute URI"),
        ("javascript:alert(1)", "uses a scheme no authorization sends a person to"),
        ("data:text/html,hello", "uses a scheme no authorization sends a person to"),
        ("https:///callback", "names no host"),
        ("https://assistant.example/" + "x" * 2000, "at most 2000 characters"),
    ],
)
async def test_a_redirect_uri_oauth_refuses_is_not(
    session: AsyncSession, uri: str, why: str
) -> None:
    async with server(session) as api:
        response = await api.post("/oauth/register", json={"redirect_uris": [uri]})

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_redirect_uri"
    assert why in response.json()["error_description"]
    assert await session.scalar(select(OAuthClient)) is None


@pytest.mark.parametrize(
    ("change", "why"),
    [
        ({"redirect_uris": []}, "redirect_uris"),
        ({"grant_types": ["refresh_token"]}, "grant_types must include authorization_code"),
        ({"grant_types": ["authorization_code", "password"]}, "password, which this server"),
        ({"response_types": ["token"]}, "response_types must be code alone"),
        ({"client_name": "x" * 101}, "client_name"),
    ],
)
async def test_metadata_the_server_cannot_honour_is_refused(
    session: AsyncSession, change: dict[str, Any], why: str
) -> None:
    async with server(session) as api:
        response = await api.post("/oauth/register", json=ASSISTANT | change)

    assert response.status_code == 400
    assert why in response.json()["error_description"]


async def test_eleven_redirect_uris_are_too_many(session: AsyncSession) -> None:
    uris = [f"http://127.0.0.1:{port}/callback" for port in range(8000, 8011)]

    async with server(session) as api:
        response = await api.post("/oauth/register", json={"redirect_uris": uris})

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_redirect_uri"


@pytest.mark.parametrize("body", [b"not json", b"[]", b'"a string"'])
async def test_a_body_that_is_no_json_object_is_refused(session: AsyncSession, body: bytes) -> None:
    async with server(session) as api:
        response = await api.post(
            "/oauth/register", content=body, headers={"Content-Type": "application/json"}
        )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_client_metadata"


async def test_registrations_are_counted_by_address(session: AsyncSession) -> None:
    async with server(session) as api:
        answers = [
            (await api.post("/oauth/register", json=ASSISTANT)).status_code for _ in range(11)
        ]

    assert answers == [201] * 10 + [429]


async def test_without_a_public_url_there_is_nothing_to_register_with(
    session: AsyncSession,
) -> None:
    async with application(session) as api:
        response = await api.post("/oauth/register", json=ASSISTANT)

    assert (response.status_code, response.json()) == (
        404,
        {"detail": "this server has no authorization server"},
    )
