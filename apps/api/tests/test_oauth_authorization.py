"""``/oauth/authorize`` and the requests a person decides on (OAuth 2.1 §4.1, ADR-0044): what a
client must ask, where it is sent, and the code a consent issues."""

from __future__ import annotations

import base64
import hashlib
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.auth.dependencies import Principal
from sef_api.auth.permissions import Permission
from sef_api.models import AuditEvent, OAuthAuthorization, Role
from sef_api.oauth import authorization as authorizations

from .factories import api_key, office
from .test_invoices_validate import application

ISSUER = "https://api.example"
WEB = "https://app.example"
SERVER = {"SEF_PUBLIC_URL": ISSUER, "SEF_WEB_ORIGINS": WEB, "SEF_WEB_URL": WEB}
CALLBACK = "https://assistant.example/callback"
VERIFIER = secrets.token_urlsafe(48)
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).decode()[:43]


@asynccontextmanager
async def server(session: AsyncSession, **variables: str) -> AsyncIterator[AsyncClient]:
    async with application(session, None, **(SERVER | variables)) as api:
        yield api


async def registered(api: AsyncClient, *uris: str) -> str:
    response = await api.post("/oauth/register", json={"redirect_uris": list(uris or [CALLBACK])})
    assert response.status_code == 201
    return str(response.json()["client_id"])


async def authorize(api: AsyncClient, client: str, **changes: str | None) -> Response:
    params = {
        "response_type": "code",
        "client_id": client,
        "redirect_uri": CALLBACK,
        "code_challenge": CHALLENGE,
        "code_challenge_method": "S256",
        "state": "xyz",
        "resource": f"{ISSUER}/mcp",
    } | changes
    return await api.get(
        "/oauth/authorize", params={k: v for k, v in params.items() if v is not None}
    )


def sent_to(response: Response) -> tuple[str, dict[str, str]]:
    """Where a redirect sends the browser, and its query's parameters."""
    assert response.status_code == 302
    parts = urlsplit(response.headers["Location"])
    query = {name: values[0] for name, values in parse_qs(parts.query).items()}
    return f"{parts.scheme}://{parts.netloc}{parts.path}", query


async def requested(session: AsyncSession, api: AsyncClient, **changes: str | None) -> str:
    """The id of a request a client made, waiting for a decision."""
    page, query = sent_to(await authorize(api, await registered(api), **changes))
    assert page == f"{WEB}/oauth/consent"
    return query["request"]


# --- the authorization endpoint ----------------------------------------------------------------


async def test_a_request_that_will_do_waits_for_a_person(session: AsyncSession) -> None:
    async with server(session) as api:
        client_id = await registered(api)
        response = await authorize(api, client_id)

    page, query = sent_to(response)
    assert page == f"{WEB}/oauth/consent"
    assert response.headers["Cache-Control"] == "no-store"
    asked = await session.get(OAuthAuthorization, query["request"])
    assert asked is not None
    assert (asked.client_id, asked.redirect_uri, asked.code_challenge) == (
        client_id,
        CALLBACK,
        CHALLENGE,
    )
    assert (asked.scopes, asked.resource, asked.state, asked.decision) == (
        ["invoices:validate"],
        f"{ISSUER}/mcp",
        "xyz",
        None,
    )
    waits = asked.expires_at - datetime.now(UTC)
    assert timedelta(minutes=9) < waits <= timedelta(minutes=10)


async def test_the_resource_and_the_redirect_uri_may_be_left_to_the_server(
    session: AsyncSession,
) -> None:
    async with server(session) as api:
        _, query = sent_to(
            await authorize(api, await registered(api), redirect_uri=None, resource=None)
        )

    asked = await session.get(OAuthAuthorization, query["request"])
    assert asked is not None
    assert (asked.redirect_uri, asked.resource) == (CALLBACK, f"{ISSUER}/mcp")


async def test_the_resource_is_compared_without_case_in_its_scheme_and_host(
    session: AsyncSession,
) -> None:
    async with server(session) as api:
        page, _ = sent_to(
            await authorize(api, await registered(api), resource="HTTPS://API.EXAMPLE/mcp/")
        )

    assert page == f"{WEB}/oauth/consent"


@pytest.mark.parametrize(
    ("changes", "why"),
    [
        ({"client_id": "unknown"}, "no client is registered with this client_id"),
        (
            {"redirect_uri": "https://elsewhere.example/callback"},
            "the redirect_uri is not one the client registered",
        ),
    ],
)
async def test_an_unknown_client_or_redirect_uri_is_answered_where_it_asked(
    session: AsyncSession, changes: dict[str, str], why: str
) -> None:
    async with server(session) as api:
        client_id = await registered(api)
        response = await authorize(api, client_id, **changes)

    assert (response.status_code, response.json()) == (400, {"detail": why})


async def test_with_two_redirect_uris_the_client_names_one(session: AsyncSession) -> None:
    async with server(session) as api:
        client_id = await registered(api, CALLBACK, "http://127.0.0.1:9000/callback")
        response = await authorize(api, client_id, redirect_uri=None)

    assert response.status_code == 400


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"response_type": "token"}, "unsupported_response_type"),
        ({"code_challenge": None, "code_challenge_method": None}, "invalid_request"),
        ({"code_challenge_method": "plain"}, "invalid_request"),
        ({"code_challenge": "too-short"}, "invalid_request"),
        ({"resource": "https://other.example/mcp"}, "invalid_target"),
        ({"resource": f"{ISSUER}/api"}, "invalid_target"),
        ({"resource": "http://["}, "invalid_target"),
        ({"scope": "invoices:validate members:manage"}, "invalid_scope"),
        ({"scope": 'invoices:validate "quoted"\\'}, "invalid_scope"),
        ({"state": "s" * 501}, "invalid_request"),
    ],
)
async def test_a_request_that_will_not_do_is_sent_back_with_its_error(
    session: AsyncSession, changes: dict[str, str | None], error: str
) -> None:
    async with server(session) as api:
        response = await authorize(api, await registered(api), **changes)

    back, query = sent_to(response)
    assert back == CALLBACK
    assert query["error"] == error
    # Only the characters OAuth allows, and nothing the client sent (RFC 6749 §4.1.2.1).
    assert query["error_description"]
    assert set(query["error_description"]) <= {
        chr(c) for c in (0x20, 0x21, *range(0x23, 0x5C), *range(0x5D, 0x7F))
    }
    # The server names itself, so the client knows whose error it reads (RFC 9207).
    assert query["iss"] == ISSUER
    assert query.get("state") == changes.get("state", "xyz")
    assert await session.scalar(select(OAuthAuthorization)) is None


async def test_without_an_address_or_a_page_there_is_no_authorizing(
    session: AsyncSession,
) -> None:
    async with application(session) as api:
        no_server = await api.get("/oauth/authorize", params={"client_id": "x"})
    async with application(session, None, SEF_PUBLIC_URL=ISSUER, SEF_WEB_ORIGINS=WEB) as api:
        no_page = await authorize(api, await registered(api))

    assert (no_server.status_code, no_page.status_code) == (404, 503)


# --- the request a person decides on -----------------------------------------------------------


async def test_a_signed_in_person_reads_what_the_client_asks(session: AsyncSession) -> None:
    primer = await office(session, "Primer Računovodstvo", "primer.example")
    async with server(session) as api:
        response = await api.post(
            "/oauth/register",
            json={"client_name": "An assistant", "redirect_uris": [CALLBACK]},
        )
        _, query = sent_to(await authorize(api, response.json()["client_id"]))
        read = await api.get(f"/oauth/requests/{query['request']}", headers=primer.as_client())

    assert read.status_code == 200
    assert read.headers["Cache-Control"] == "no-store"
    answer = read.json()
    assert (answer["client_name"], answer["redirect_uri"], answer["scopes"]) == (
        "An assistant",
        CALLBACK,
        ["invoices:validate"],
    )


async def test_only_a_person_decides(session: AsyncSession) -> None:
    primer = await office(session, "Primer Računovodstvo", "primer.example")
    key = await api_key(session, primer.organization, primer.client)
    async with server(session) as api:
        request_id = await requested(session, api)
        anonymous = await api.get(f"/oauth/requests/{request_id}")
        with_key = await api.post(f"/oauth/requests/{request_id}/approval", headers=key.header())

    assert anonymous.status_code == 401
    assert (with_key.status_code, with_key.json()) == (
        403,
        {"detail": "a person decides what a client may do: sign in to decide, an API key cannot"},
    )


async def test_an_approval_sends_the_client_a_code_and_is_recorded(session: AsyncSession) -> None:
    primer = await office(session, "Primer Računovodstvo", "primer.example")
    async with server(session) as api:
        request_id = await requested(session, api)
        approved = await api.post(
            f"/oauth/requests/{request_id}/approval", headers=primer.as_client()
        )
        again = await api.post(f"/oauth/requests/{request_id}/approval", headers=primer.as_owner())
        read = await api.get(f"/oauth/requests/{request_id}", headers=primer.as_owner())

    assert approved.status_code == 200
    assert approved.headers["Cache-Control"] == "no-store"
    back, query = sent_to_uri(approved.json()["redirect_uri"])
    assert back == CALLBACK
    assert (query["state"], query["iss"]) == ("xyz", ISSUER)
    asked = await session.get(OAuthAuthorization, request_id)
    assert asked is not None
    await session.refresh(asked)
    assert (asked.decision, asked.organization_id, asked.user_id) == (
        "approved",
        primer.organization.id,
        primer.client.id,
    )
    assert asked.code_sha256 == hashlib.sha256(query["code"].encode()).hexdigest()
    assert asked.code_expires_at is not None
    assert timedelta(minutes=1) < asked.code_expires_at - datetime.now(UTC) <= timedelta(minutes=2)
    event = await session.scalar(select(AuditEvent))
    assert event is not None
    assert (event.action, event.actor, event.detail) == (
        "oauth.client_authorized",
        primer.client.id,
        {"client_id": asked.client_id, "scopes": ["invoices:validate"]},
    )
    # Decided once, the request waits for nobody.
    assert again.status_code == read.status_code == 404


async def test_of_two_decisions_at_once_only_the_first_counts(session: AsyncSession) -> None:
    """Two members press at once: each read the request while it waited, and the one whose
    decision lands second decides nothing, neither approving it again nor refusing it."""
    primer = await office(session, "Primer Računovodstvo", "primer.example")
    owner = Principal(primer.owner.id, primer.organization.id, Role.OWNER)
    client = primer.client.id
    async with server(session) as api:
        request_id = await requested(session, api)
        seen = await authorizations.pending(session, request_id)
        assert seen is not None
        # Held as the other request's session holds it: read while it waited, not read again.
        session.expunge(seen)
        first = await api.post(f"/oauth/requests/{request_id}/approval", headers=primer.as_client())

        second = await authorizations.approve(session, seen, owner)
        refused = await authorizations.refuse(session, seen)

    assert first.status_code == 200
    assert second is None
    assert refused is False
    asked = await session.get(OAuthAuthorization, request_id)
    assert asked is not None
    await session.refresh(asked)
    _, query = sent_to_uri(first.json()["redirect_uri"])
    assert (asked.decision, asked.user_id) == ("approved", client)
    assert asked.code_sha256 == hashlib.sha256(query["code"].encode()).hexdigest()
    assert len((await session.scalars(select(AuditEvent))).all()) == 1


async def test_a_refusal_sends_the_client_back_with_access_denied(session: AsyncSession) -> None:
    primer = await office(session, "Primer Računovodstvo", "primer.example")
    async with server(session) as api:
        request_id = await requested(session, api)
        refused = await api.post(
            f"/oauth/requests/{request_id}/refusal", headers=primer.as_client()
        )
        approved = await api.post(
            f"/oauth/requests/{request_id}/approval", headers=primer.as_client()
        )

    back, query = sent_to_uri(refused.json()["redirect_uri"])
    assert (back, query["error"], query["state"], query["iss"]) == (
        CALLBACK,
        "access_denied",
        "xyz",
        ISSUER,
    )
    assert "code" not in query
    asked = await session.get(OAuthAuthorization, request_id)
    assert asked is not None
    await session.refresh(asked)
    assert (asked.decision, asked.code_sha256) == ("refused", None)
    assert approved.status_code == 404


async def test_an_expired_request_waits_for_nobody(session: AsyncSession) -> None:
    primer = await office(session, "Primer Računovodstvo", "primer.example")
    async with server(session) as api:
        request_id = await requested(session, api)
        await session.execute(
            update(OAuthAuthorization)
            .where(OAuthAuthorization.id == request_id)
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        read = await api.get(f"/oauth/requests/{request_id}", headers=primer.as_client())
        approved = await api.post(
            f"/oauth/requests/{request_id}/approval", headers=primer.as_client()
        )

    assert read.status_code == approved.status_code == 404


async def test_a_role_grants_only_its_own_permissions(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        authorizations,
        "SCOPES",
        MappingProxyType(
            {
                "invoices:validate": Permission.INVOICES_VALIDATE,
                "members:manage": Permission.MEMBERS_MANAGE,
            }
        ),
    )
    primer = await office(session, "Primer Računovodstvo", "primer.example")
    async with server(session) as api:
        both = await requested(session, api, scope="invoices:validate members:manage")
        approved = await api.post(f"/oauth/requests/{both}/approval", headers=primer.as_client())
        managing = await requested(session, api, scope="members:manage")
        refused = await api.post(f"/oauth/requests/{managing}/approval", headers=primer.as_client())

    asked = await session.get(OAuthAuthorization, both)
    assert asked is not None
    await session.refresh(asked)
    assert approved.status_code == 200
    assert asked.scopes == ["invoices:validate"]
    assert (refused.status_code, refused.json()) == (
        403,
        {"detail": "your role grants none of the scopes the client asks for"},
    )


def sent_to_uri(uri: str) -> tuple[str, dict[str, Any]]:
    parts = urlsplit(uri)
    query = {name: values[0] for name, values in parse_qs(parts.query).items()}
    return f"{parts.scheme}://{parts.netloc}{parts.path}", query
