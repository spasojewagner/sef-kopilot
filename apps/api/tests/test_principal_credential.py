"""Which credential a caller came with: in person, with an API key, or through an MCP client
under a person's consent; what only a person may do, and what the audit log records."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api import audit
from sef_api.api_keys.service import Grant
from sef_api.auth.dependencies import Consent, Principal, check_again
from sef_api.auth.permissions import Permission
from sef_api.models import AuditAction, AuditEvent, OAuthAuthorization, OAuthClient, Role

from .factories import office

CALLBACK = "https://assistant.example/callback"


def test_only_a_person_who_came_themselves_is_in_person() -> None:
    person = Principal(uuid.uuid4(), uuid.uuid4(), Role.OWNER)
    keyed = Principal(
        person.user_id, person.organization_id, Role.OWNER, key=Grant(uuid.uuid4(), frozenset())
    )
    assistant = Principal(
        person.user_id,
        person.organization_id,
        Role.OWNER,
        scopes=frozenset({Permission.INVOICES_VALIDATE}),
        consent=Consent("a-1", "c-1"),
    )

    assert [p.in_person for p in (person, keyed, assistant)] == [True, False, False]


async def consented(session: AsyncSession) -> Principal:
    """Primer's client, through an MCP client they let validate invoices for them."""
    primer = await office(session, "Primer Računovodstvo", "primer.example")
    session.add(
        OAuthClient(
            id="c-1", name="Asistent", redirect_uris=[CALLBACK], grant_types=["authorization_code"]
        )
    )
    await session.flush()
    now = datetime.now(UTC)
    session.add(
        OAuthAuthorization(
            id="a-1",
            client_id="c-1",
            redirect_uri=CALLBACK,
            code_challenge="x" * 43,
            scopes=["invoices:validate"],
            resource="https://api.example/mcp",
            expires_at=now,
            decision="approved",
            decided_at=now,
            organization_id=primer.organization.id,
            user_id=primer.client.id,
            code_sha256="0" * 64,
            code_expires_at=now,
        )
    )
    await session.flush()
    return Principal(
        primer.client.id,
        primer.organization.id,
        Role.CLIENT,
        scopes=frozenset({Permission.INVOICES_VALIDATE}),
        consent=Consent("a-1", "c-1"),
    )


async def test_a_long_request_checks_the_consent_again(session: AsyncSession) -> None:
    """Work that outlasts the moment the caller was checked is checked again before it changes
    anything: a consent revoked meanwhile stops it, as a revoked key would."""
    caller = await consented(session)

    still = await check_again(session, caller, Permission.INVOICES_VALIDATE)
    await session.execute(
        update(OAuthAuthorization)
        .where(OAuthAuthorization.id == "a-1")
        .values(revoked_at=datetime.now(UTC))
    )
    with pytest.raises(HTTPException) as refused:
        await check_again(session, caller, Permission.INVOICES_VALIDATE)

    assert still.role is Role.CLIENT
    assert (refused.value.status_code, refused.value.detail) == (
        401,
        "the consent behind this access token was revoked",
    )


async def test_the_audit_log_names_the_client_an_act_came_through(session: AsyncSession) -> None:
    caller = await consented(session)

    audit.record(session, caller, AuditAction.OAUTH_CLIENT_AUTHORIZED, detail={"note": "test"})
    await session.flush()

    event = await session.scalar(select(AuditEvent))
    assert event is not None
    assert (event.actor, event.key_id, event.oauth_client_id) == (caller.user_id, None, "c-1")
