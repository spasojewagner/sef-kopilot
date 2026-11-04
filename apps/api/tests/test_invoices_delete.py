"""Deleting a stored invoice: the document and its report go, the quota makes room, and a
client deletes only what they submitted."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.models import StoredInvoice

from .factories import Office, office, stored_invoice
from .test_invoices_validate import VALID, XML, application

MIB = 1024 * 1024
NOT_FOUND = {"detail": "no such invoice in this organization"}


@pytest.fixture
async def primer(session: AsyncSession) -> Office:
    return await office(session, "Primer Računovodstvo", "primer.example")


async def stored(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(StoredInvoice)) or 0


async def test_a_deleted_invoice_is_gone_with_its_document_and_report(
    api: AsyncClient, primer: Office, session: AsyncSession
) -> None:
    location = (
        await api.post("/invoices", content=VALID, headers=XML | primer.as_client())
    ).headers["Location"]

    deleted = await api.delete(location, headers=primer.as_client())

    assert deleted.status_code == 204
    for path in (location, f"{location}/content"):
        response = await api.get(path, headers=primer.as_owner())
        assert (response.status_code, response.json()) == (404, NOT_FOUND)
    assert await stored(session) == 0


async def test_a_client_deletes_only_the_invoices_they_submitted(
    api: AsyncClient, primer: Office, session: AsyncSession
) -> None:
    own = await stored_invoice(session, primer.organization, primer.client)
    other = await stored_invoice(session, primer.organization, primer.owner)

    refused = await api.delete(f"/invoices/{other.id}", headers=primer.as_client())
    assert (refused.status_code, refused.json()) == (404, NOT_FOUND)
    assert (await api.delete(f"/invoices/{own.id}", headers=primer.as_client())).status_code == 204
    accountant = await api.delete(f"/invoices/{other.id}", headers=primer.as_accountant())
    assert accountant.status_code == 204
    assert await stored(session) == 0


async def test_deleting_makes_room_in_the_quota(session: AsyncSession, primer: Office) -> None:
    large = await stored_invoice(session, primer.organization, primer.owner, b"x" * (MIB - 1024))

    async with application(session, SEF_MAX_STORED_BYTES=str(MIB)) as api:
        full = await api.post("/invoices", content=VALID, headers=XML | primer.as_owner())
        await api.delete(f"/invoices/{large.id}", headers=primer.as_owner())
        room = await api.post("/invoices", content=VALID, headers=XML | primer.as_owner())

    assert (full.status_code, room.status_code) == (507, 201)


async def test_an_invoice_that_does_not_exist_cannot_be_deleted(
    api: AsyncClient, primer: Office
) -> None:
    response = await api.delete(
        "/invoices/00000000-0000-4000-8000-000000000000", headers=primer.as_owner()
    )

    assert (response.status_code, response.json()) == (404, NOT_FOUND)
