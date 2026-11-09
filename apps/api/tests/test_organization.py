"""``/organization`` on PostgreSQL: every member sees how long the organization keeps its stored
invoices, an owner sets it, and the audit log records each change (ADR-0039). Who may call what,
and that no organization reaches into another, is checked with every endpoint in
``test_access_control.py``; a change by an owner demoted meanwhile, in ``test_concurrency.py``."""

from __future__ import annotations

from collections import Counter
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.models import AuditAction, AuditEvent, Organization

from .factories import Office, office


@pytest.fixture
async def primer(session: AsyncSession) -> Office:
    return await office(session, "Primer Računovodstvo", "primer.example")


async def period(session: AsyncSession, primer: Office) -> int | None:
    return await session.scalar(
        select(Organization.invoice_retention_days).where(Organization.id == primer.organization.id)
    )


async def changes(session: AsyncSession) -> Counter[tuple[Any, Any]]:
    """What each recorded change of the period was and became, and how many times; the events
    of one transaction have one time, so they have no order here."""
    events = await session.scalars(
        select(AuditEvent).where(AuditEvent.action == AuditAction.ORGANIZATION_RETENTION_SET)
    )
    return Counter((event.detail["from"], event.detail["to"]) for event in events)


@pytest.mark.parametrize("member", ["owner", "accountant", "client"])
async def test_every_member_sees_how_long_the_organization_keeps_its_invoices(
    api: AsyncClient, primer: Office, member: str
) -> None:
    headers = {
        "owner": primer.as_owner,
        "accountant": primer.as_accountant,
        "client": primer.as_client,
    }[member]()

    response = await api.get("/organization", headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "id": str(primer.organization.id),
        "name": "Primer Računovodstvo",
        "invoice_retention_days": None,
        "sef_key_set_at": None,
        "model_key": None,
    }


async def test_an_owner_sets_the_period_and_the_audit_log_records_who_and_what_it_was(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    setting = await api.patch(
        "/organization", json={"invoice_retention_days": 30}, headers=primer.as_owner()
    )
    shown = await api.get("/organization", headers=primer.as_client())

    assert setting.status_code == 200
    assert setting.json()["invoice_retention_days"] == 30
    assert shown.json()["invoice_retention_days"] == 30
    assert await period(session, primer) == 30
    event = await session.scalar(select(AuditEvent))
    assert event is not None
    assert (event.organization_id, event.actor, event.key_id) == (
        primer.organization.id,
        primer.owner.id,
        None,
    )
    assert (event.action, event.invoice_id, event.repair_id) == (
        AuditAction.ORGANIZATION_RETENTION_SET,
        None,
        None,
    )
    assert event.detail == {"from": None, "to": 30}


async def test_null_keeps_every_invoice_again(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    for days in (30, 365, None):
        response = await api.patch(
            "/organization", json={"invoice_retention_days": days}, headers=primer.as_owner()
        )
        assert response.status_code == 200

    assert response.json()["invoice_retention_days"] is None
    assert await period(session, primer) is None
    assert await changes(session) == Counter([(None, 30), (30, 365), (365, None)])


@pytest.mark.parametrize("body", [{"invoice_retention_days": 30}, {}])
async def test_a_request_that_changes_nothing_records_nothing(
    api: AsyncClient, session: AsyncSession, primer: Office, body: dict[str, Any]
) -> None:
    """The period it has already, or no period at all: the organization is shown as it is."""
    await api.patch("/organization", json={"invoice_retention_days": 30}, headers=primer.as_owner())

    response = await api.patch("/organization", json=body, headers=primer.as_owner())

    assert response.status_code == 200
    assert response.json()["invoice_retention_days"] == 30
    assert await changes(session) == Counter([(None, 30)])


@pytest.mark.parametrize(
    "body",
    [
        {"invoice_retention_days": 0},
        {"invoice_retention_days": -30},
        {"invoice_retention_days": 3651},
        {"invoice_retention_days": 30.5},
        {"invoice_retention_days": "forever"},
        {"name": "Drugo ime"},
    ],
    ids=["zero", "negative", "over ten years", "a fraction", "not a number", "another field"],
)
async def test_a_period_out_of_bounds_or_another_change_is_refused(
    api: AsyncClient, session: AsyncSession, primer: Office, body: dict[str, Any]
) -> None:
    response = await api.patch("/organization", json=body, headers=primer.as_owner())

    assert response.status_code == 422
    assert await period(session, primer) is None
    assert not await changes(session)


@pytest.mark.parametrize("days", [1, 3650])
async def test_the_bounds_themselves_are_periods(
    api: AsyncClient, session: AsyncSession, primer: Office, days: int
) -> None:
    response = await api.patch(
        "/organization", json={"invoice_retention_days": days}, headers=primer.as_owner()
    )

    assert response.status_code == 200
    assert await period(session, primer) == days


async def test_an_accountant_cannot_set_the_period(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    response = await api.patch(
        "/organization", json={"invoice_retention_days": 1}, headers=primer.as_accountant()
    )

    assert response.status_code == 403
    assert await period(session, primer) is None
    assert not await changes(session)
