"""API keys on PostgreSQL: issuing one, a machine client acting for its member with it, and
listing and revoking keys."""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
import tomllib
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.api_keys import service
from sef_api.auth.permissions import Permission
from sef_api.auth.tokens import new_opaque_token
from sef_api.db import Database
from sef_api.models import ApiKey, Membership, Organization, Role, StoredInvoice, User

from .conftest import REPOSITORY_ROOT
from .factories import NO_PASSWORD, Office, api_key, join, office, stored_invoice
from .test_invoices_validate import Scripted, application, using

INVOICE = (
    REPOSITORY_ROOT / "fixtures" / "invoices" / "synthetic" / "srb-final-invoice.xml"
).read_bytes()
XML = {"Content-Type": "application/xml"}


@pytest.fixture
async def primer(session: AsyncSession) -> Office:
    return await office(session, "Primer Računovodstvo", "primer.example")


async def issue(api: AsyncClient, caller: dict[str, str], **change: Any) -> Any:
    request = {"name": "Pantheon", "permissions": ["invoices:submit"]} | change
    return await api.post("/api-keys", json=request, headers=caller)


def bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


async def keys(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(ApiKey)) or 0


# --- issuing -----------------------------------------------------------------------------------


async def test_a_member_issues_a_key_and_sees_it_once(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    response = await issue(
        api,
        primer.as_client(),
        name="  Pantheon ",
        permissions=["invoices:validate", "invoices:submit", "invoices:validate"],
    )

    assert response.status_code == 201
    assert response.headers["Cache-Control"] == "no-store"
    issued = response.json()
    key = issued.pop("key")
    assert key.startswith("sefk_")
    assert len(key) == 48
    assert issued == {
        "id": issued["id"],
        "name": "Pantheon",
        "prefix": key[:12],
        "permissions": ["invoices:submit", "invoices:validate"],
        "acts_for": str(primer.client.id),
        "created_at": issued["created_at"],
        "expires_at": None,
        "last_used_at": None,
    }
    row = (await session.execute(select(ApiKey.__table__))).one()
    assert row.digest == hashlib.sha256(key.encode()).hexdigest()
    assert [column for column in row if key in str(column)] == []


async def test_a_machine_client_acts_for_the_member_whose_key_it_has(
    api: AsyncClient, primer: Office
) -> None:
    key = (await issue(api, primer.as_client())).json()["key"]

    stored = await api.post("/invoices", content=INVOICE, headers=XML | bearer(key))
    listed = await api.get("/invoices", headers=bearer(key))

    assert stored.status_code == 201
    assert stored.json()["submitted_by"] == str(primer.client.id)
    assert [invoice["id"] for invoice in listed.json()["invoices"]] == [stored.json()["id"]]


async def test_a_key_allows_only_what_it_holds(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    key = await api_key(session, primer.organization, primer.client, Permission.INVOICES_VALIDATE)

    validated = await api.post("/invoices/validate", content=INVOICE, headers=XML | key.header())
    listed = await api.get("/invoices", headers=key.header())

    assert validated.status_code == 200
    assert (listed.status_code, listed.json()) == (
        403,
        {"detail": "requires the permission invoices:submit"},
    )


async def test_a_key_never_allows_more_than_its_members_role_grants_now(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    """An accountant's key sees every invoice of the office until the accountant is a client."""
    owners = await stored_invoice(session, primer.organization, primer.owner)
    key = await api_key(
        session,
        primer.organization,
        primer.accountant,
        Permission.INVOICES_SUBMIT,
        Permission.INVOICES_MANAGE,
    )
    before = await api.get("/invoices", headers=key.header())

    await session.execute(
        update(Membership)
        .where(
            Membership.organization_id == primer.organization.id,
            Membership.user_id == primer.accountant.id,
        )
        .values(role=Role.CLIENT)
    )
    after = await api.get("/invoices", headers=key.header())

    assert [invoice["id"] for invoice in before.json()["invoices"]] == [str(owners.id)]
    assert after.json()["invoices"] == []


async def test_a_key_without_invoices_manage_sees_only_its_members_invoices(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    """Even an owner's: what a key sees is what its permissions allow as well as the role."""
    clients = await stored_invoice(session, primer.organization, primer.client)
    owners = await stored_invoice(session, primer.organization, primer.owner)
    key = await api_key(session, primer.organization, primer.owner, Permission.INVOICES_SUBMIT)

    listed = await api.get("/invoices", headers=key.header())
    read = await api.get(f"/invoices/{clients.id}", headers=key.header())

    assert [invoice["id"] for invoice in listed.json()["invoices"]] == [str(owners.id)]
    assert read.status_code == 404


async def test_a_key_revoked_while_the_invoice_is_validated_stores_nothing(
    session: AsyncSession, primer: Office
) -> None:
    """The upload and the validation outlast the moment the key was checked, so it is checked
    again where the invoice is stored, as the membership is."""
    key = await api_key(session, primer.organization, primer.client, Permission.INVOICES_SUBMIT)
    scripted = Scripted()
    scripted.held = True

    async with application(session, using(scripted)) as api:
        upload = asyncio.create_task(
            api.post("/invoices", content=INVOICE, headers=XML | key.header())
        )
        await asyncio.wait_for(scripted.entered.wait(), 5)
        await session.execute(update(ApiKey).values(revoked_at=datetime.now(UTC)))
        scripted.release.set()
        response = await upload

    assert (response.status_code, response.json()) == (
        401,
        {"detail": "invalid, expired or revoked API key"},
    )
    assert await session.scalar(select(func.count()).select_from(StoredInvoice)) == 0


async def test_a_member_cannot_give_a_key_what_their_role_does_not_grant(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    response = await issue(
        api, primer.as_client(), permissions=["invoices:submit", "invoices:manage"]
    )

    assert (response.status_code, response.json()) == (
        403,
        {"detail": "your role does not grant invoices:manage"},
    )
    assert await keys(session) == 0


@pytest.mark.parametrize("permission", ["members:read", "members:manage", "api_keys:issue"])
async def test_a_key_holds_only_permissions_for_work_on_invoices(
    api: AsyncClient, session: AsyncSession, primer: Office, permission: str
) -> None:
    response = await issue(api, primer.as_owner(), permissions=["invoices:submit", permission])

    assert response.status_code == 422
    assert await keys(session) == 0


async def test_a_key_cannot_issue_keys(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    key = await api_key(session, primer.organization, primer.owner)

    response = await issue(api, key.header())

    assert (response.status_code, response.json()) == (
        403,
        {"detail": "requires the permission api_keys:issue"},
    )
    assert await keys(session) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"name": "   "},
        {"name": "x" * 101},
        {"permissions": []},
        {"expires_at": "2026-01-01T00:00:00Z"},
        {"expires_at": "2099-01-01T00:00:00"},
    ],
    ids=["blank name", "long name", "no permission", "expiry in the past", "expiry without zone"],
)
async def test_a_request_for_a_key_is_checked(
    api: AsyncClient, session: AsyncSession, primer: Office, change: dict[str, Any]
) -> None:
    response = await issue(api, primer.as_owner(), **change)

    assert response.status_code == 422
    assert await keys(session) == 0


async def test_a_key_works_until_it_expires(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    soon = datetime.now(UTC) + timedelta(hours=1)
    issued = (await issue(api, primer.as_client(), expires_at=soon.isoformat())).json()
    working = await api.get("/invoices", headers=bearer(issued["key"]))

    await session.execute(update(ApiKey).values(expires_at=datetime.now(UTC)))
    expired = await api.get("/invoices", headers=bearer(issued["key"]))

    assert datetime.fromisoformat(issued["expires_at"]) == soon
    assert (working.status_code, expired.status_code) == (200, 401)


@pytest.mark.parametrize("state", ["unknown", "revoked", "expired"])
async def test_a_key_that_does_not_work_is_refused(
    api: AsyncClient, session: AsyncSession, primer: Office, state: str
) -> None:
    moment = datetime.now(UTC)
    key = await api_key(
        session,
        primer.organization,
        primer.client,
        Permission.INVOICES_SUBMIT,
        revoked_at=moment if state == "revoked" else None,
        expires_at=moment if state == "expired" else None,
    )
    sent = "sefk_" + "A" * 43 if state == "unknown" else key.secret

    response = await api.get("/invoices", headers=bearer(sent))

    assert (response.status_code, response.json()) == (
        401,
        {"detail": "invalid, expired or revoked API key"},
    )
    assert response.headers["WWW-Authenticate"] == 'Bearer error="invalid_token"'


async def test_a_removed_members_keys_go_and_do_not_come_back_with_them(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    key = await api_key(session, primer.organization, primer.accountant)

    removed = await api.delete(f"/members/{primer.accountant.id}", headers=primer.as_owner())
    await join(session, primer.organization, primer.accountant, Role.ACCOUNTANT)  # invited back
    response = await api.get("/invoices", headers=key.header())

    assert removed.status_code == 204
    assert response.status_code == 401
    assert await keys(session) == 0


async def test_the_key_of_a_deactivated_account_is_refused(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    key = await api_key(session, primer.organization, primer.client, Permission.INVOICES_SUBMIT)

    await session.execute(update(User).where(User.id == primer.client.id).values(is_active=False))
    response = await api.get("/invoices", headers=key.header())

    assert (response.status_code, response.json()) == (
        401,
        {"detail": "the account or its membership is no longer active"},
    )


async def test_who_am_i_names_the_member_a_key_acts_for(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    key = await api_key(session, primer.organization, primer.client, Permission.INVOICES_VALIDATE)

    response = await api.get("/auth/me", headers=key.header())

    assert response.status_code == 200
    assert response.json()["user"]["email"] == "client@primer.example"
    assert response.json()["role"] == "client"


# --- listing and revoking ----------------------------------------------------------------------


async def test_a_member_lists_the_keys_that_work_newest_first_without_the_keys(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    moment = datetime.now(UTC)
    await api_key(session, primer.organization, primer.client, revoked_at=moment)
    await api_key(session, primer.organization, primer.client, expires_at=moment)
    older = await api_key(
        session,
        primer.organization,
        primer.client,
        Permission.INVOICES_SUBMIT,
        created_at=moment - timedelta(days=1),
    )
    issued = (await issue(api, primer.as_client(), name="Minimax")).json()

    listed = await api.get("/api-keys", headers=primer.as_client())

    assert listed.status_code == 200
    assert [key["id"] for key in listed.json()] == [issued["id"], str(older.row.id)]
    assert listed.json()[0] == {field: value for field, value in issued.items() if field != "key"}


async def test_an_owner_sees_and_revokes_every_key_of_the_organization(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    clients = await api_key(session, primer.organization, primer.client, Permission.INVOICES_SUBMIT)
    accountants = await api_key(session, primer.organization, primer.accountant)

    listed = await api.get("/api-keys", headers=primer.as_owner())
    revoked = await api.delete(f"/api-keys/{clients.row.id}", headers=primer.as_owner())

    assert sorted(key["id"] for key in listed.json()) == sorted(
        [str(clients.row.id), str(accountants.row.id)]
    )
    assert revoked.status_code == 204
    assert (await api.get("/invoices", headers=clients.header())).status_code == 401
    assert (await api.get("/invoices", headers=accountants.header())).status_code == 200


async def test_a_member_without_api_keys_manage_sees_and_revokes_only_their_own(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    clients = await api_key(session, primer.organization, primer.client, Permission.INVOICES_SUBMIT)
    accountants = await api_key(session, primer.organization, primer.accountant)

    listed = await api.get("/api-keys", headers=primer.as_accountant())
    refused = await api.delete(f"/api-keys/{clients.row.id}", headers=primer.as_accountant())

    assert [key["id"] for key in listed.json()] == [str(accountants.row.id)]
    assert (refused.status_code, refused.json()) == (
        404,
        {"detail": "no such API key in this organization"},
    )
    assert (await api.get("/invoices", headers=clients.header())).status_code == 200


async def test_a_revoked_key_stops_working_and_revoking_it_again_changes_nothing(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    key = await api_key(session, primer.organization, primer.client, Permission.INVOICES_SUBMIT)

    revoked = await api.delete(f"/api-keys/{key.row.id}", headers=primer.as_client())
    await session.refresh(key.row)
    first = key.row.revoked_at
    again = await api.delete(f"/api-keys/{key.row.id}", headers=primer.as_client())
    await session.refresh(key.row)

    assert (revoked.status_code, again.status_code) == (204, 204)
    assert first is not None
    assert key.row.revoked_at == first
    assert (await api.get("/invoices", headers=key.header())).status_code == 401
    assert (await api.get("/api-keys", headers=primer.as_client())).json() == []


async def test_an_unknown_key_is_not_found(api: AsyncClient, primer: Office) -> None:
    response = await api.delete(f"/api-keys/{primer.organization.id}", headers=primer.as_owner())

    assert response.status_code == 404


# --- how many keys a member may have -----------------------------------------------------------


async def test_a_member_has_at_most_twenty_keys_that_work(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    moment = datetime.now(UTC)
    for _ in range(service.MAX_KEYS_PER_MEMBER - 1):
        await api_key(session, primer.organization, primer.client, Permission.INVOICES_SUBMIT)
    await api_key(session, primer.organization, primer.client, revoked_at=moment)
    await api_key(session, primer.organization, primer.client, expires_at=moment)

    last = await issue(api, primer.as_client())
    over = await issue(api, primer.as_client())
    colleagues = await issue(api, primer.as_accountant())

    assert last.status_code == 201
    assert (over.status_code, over.json()) == (
        409,
        {"detail": "a member has at most 20 API keys; revoke one first"},
    )
    assert colleagues.status_code == 201


async def test_keys_issued_at_the_same_moment_cannot_exceed_the_limit(
    committed_database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Counting a member's keys and issuing one more happen under the organization's lock on
    its keys: two requests with room for one issue one, even when both count before either
    issues."""
    async with committed_database.sessions() as setup:
        primer = Organization(name="Primer")
        ana = User(email="ana@primer.example", password_hash=NO_PASSWORD)
        setup.add_all([primer, ana])
        await setup.flush()
        await join(setup, primer, ana, Role.CLIENT)
        for _ in range(service.MAX_KEYS_PER_MEMBER - 1):
            await api_key(setup, primer, ana, Permission.INVOICES_SUBMIT)
        await setup.commit()
    real = service.working_keys

    async def slowly(*arguments: Any) -> int:
        counted = await real(*arguments)
        await asyncio.sleep(0.2)  # the other request counts meanwhile, if nothing stops it
        return counted

    monkeypatch.setattr(service, "working_keys", slowly)

    async def issue_one() -> str:
        async with committed_database.sessions() as session:
            try:
                await service.issue(
                    session,
                    organization_id=primer.id,
                    user_id=ana.id,
                    role=Role.CLIENT,
                    name="ERP",
                    permissions=[Permission.INVOICES_SUBMIT],
                )
            except service.TooManyKeysError:
                return "refused"
            return "issued"

    results = await asyncio.gather(issue_one(), issue_one())

    assert sorted(results) == ["issued", "refused"]


async def test_openapi_documents_the_api_keys(client: AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()
    paths = schema["paths"]
    request = schema["components"]["schemas"]["KeyRequest"]["properties"]

    for path, method in [
        ("/api-keys", "post"),
        ("/api-keys", "get"),
        ("/api-keys/{key_id}", "delete"),
    ]:
        assert paths[path][method]["tags"] == ["api keys"]
        assert paths[path][method]["security"] == [{"access token or API key": []}]
    assert set(paths["/api-keys"]["post"]["responses"]) == {"201", "403", "409", "422"}
    assert set(paths["/api-keys/{key_id}"]["delete"]["responses"]) == {"204", "404", "422"}
    assert request["permissions"]["items"]["enum"] == [
        "invoices:validate",
        "invoices:submit",
        "invoices:manage",
    ]


def entropy(text: str) -> float:
    """Shannon entropy in bits per character, as gitleaks measures a match."""
    return -sum(n / len(text) * math.log2(n / len(text)) for n in Counter(text).values())


def test_the_secret_scan_recognizes_a_key() -> None:
    """``.gitleaks.toml`` describes the keys this API issues, so that a leaked one is caught
    before it is committed and in the history."""
    rules = tomllib.loads((REPOSITORY_ROOT / ".gitleaks.toml").read_text(encoding="utf-8"))
    (rule,) = [rule for rule in rules["rules"] if rule["id"] == "sef-kopilot-api-key"]
    keys = [service.PREFIX + new_opaque_token() for _ in range(200)]

    assert all(re.fullmatch(rule["regex"], key) for key in keys)
    assert all(any(word in key for word in rule["keywords"]) for key in keys)
    assert min(map(entropy, keys)) > rule["entropy"]
    assert entropy(service.PREFIX + "A" * 43) < rule["entropy"]
