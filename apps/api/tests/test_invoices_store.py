"""``POST /invoices``: an invoice kept for the caller's organization with the validator's report
on it, within the organization's storage quota."""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from einvoice_core.pipeline import validate as validate_with_the_core
from sef_api.db import Database
from sef_api.invoices import store
from sef_api.invoices.validation import Validation, outcome
from sef_api.models import Membership, Organization, StoredInvoice, User

from .factories import NO_PASSWORD, Office, office
from .test_invoices_validate import VALID, XML, Scripted, application, using

MIB = 1024 * 1024


@pytest.fixture
async def primer(session: AsyncSession) -> Office:
    return await office(session, "Primer Računovodstvo", "primer.example")


async def submit(api: AsyncClient, member: dict[str, str], content: Any, **params: str) -> Any:
    return await api.post("/invoices", params=params, content=content, headers=XML | member)


async def stored_count(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(StoredInvoice)) or 0


def filler(organization: Organization, size: int) -> StoredInvoice:
    """A stored invoice of ``size`` bytes, as a quota sees it."""
    content = b"x" * size
    return StoredInvoice(
        organization_id=organization.id,
        profile="srb",
        valid=False,
        report={"profile": "srb", "valid": False, "violations": [], "layers": []},
        report_size=64,
        content=content,
        size=size,
        sha256=hashlib.sha256(content).hexdigest(),
    )


async def test_an_invoice_is_stored_with_its_report_and_what_the_validator_read(
    api: AsyncClient, primer: Office, session: AsyncSession
) -> None:
    response = await submit(api, primer.as_client(), VALID)

    assert response.status_code == 201
    body = response.json()
    assert response.headers["Location"] == f"/invoices/{body['id']}"
    assert response.headers["Cache-Control"] == "no-store"
    assert body["submitted_by"] == str(primer.client.id)
    assert (body["profile"], body["valid"], body["size"]) == ("srb", True, len(VALID))
    assert body["sha256"] == hashlib.sha256(VALID).hexdigest()
    assert body["summary"] == {
        "document_type": "Invoice",
        "number": "RF-2026-000124",
        "issue_date": "2026-10-05",
        "currency": "RSD",
        "seller": "Primer Softver d.o.o.",
        "buyer": "Ogledni Kupac d.o.o.",
        "payable_amount": "8400.00",
    }
    assert body["report"] == validate_with_the_core(VALID, "srb").model_dump(mode="json")
    stored = await session.scalar(select(StoredInvoice))
    assert stored is not None
    assert stored.organization_id == primer.organization.id
    assert body["submitted_at"] == stored.created_at.isoformat().replace("+00:00", "Z")
    assert body["validated_at"] == body["submitted_at"]
    assert await session.scalar(select(StoredInvoice.content)) == VALID


async def test_a_document_the_validator_cannot_read_is_stored_with_the_report_that_says_why(
    api: AsyncClient, primer: Office
) -> None:
    response = await submit(api, primer.as_accountant(), b"<Invoice><cbc:ID>", profile="peppol")

    assert response.status_code == 201
    body = response.json()
    assert (body["profile"], body["valid"], body["summary"]) == ("peppol", False, None)
    assert [v["code"] for v in body["report"]["violations"]] == ["UNREADABLE"]


@pytest.mark.parametrize(
    ("content", "headers", "status_code"),
    [
        (VALID, {"Content-Type": "text/plain"}, 415),
        (b"<x>" + b"<y/>" * 30_000 + b"</x>", XML, 413),
    ],
    ids=["not-xml", "too-many-elements"],
)
async def test_an_invoice_the_api_refuses_is_not_stored(
    api: AsyncClient,
    primer: Office,
    session: AsyncSession,
    content: bytes,
    headers: dict[str, str],
    status_code: int,
) -> None:
    response = await api.post("/invoices", content=content, headers=headers | primer.as_owner())

    assert response.status_code == status_code
    assert await stored_count(session) == 0


async def test_an_organization_stores_no_more_than_its_quota(
    session: AsyncSession, primer: Office
) -> None:
    """Its documents and their reports together: the documents alone would fit. Another
    organization's do not count, and validating without storing still works."""
    ogled = await office(session, "Ogled", "ogled.example")
    session.add(filler(primer.organization, MIB - len(VALID)))
    await session.flush()

    async with application(session, SEF_MAX_STORED_BYTES=str(MIB)) as api:
        full = await submit(api, primer.as_owner(), VALID)
        validated = await api.post(
            "/invoices/validate", content=VALID, headers=XML | primer.as_owner()
        )
        elsewhere = await submit(api, ogled.as_owner(), VALID)

    assert (full.status_code, full.json()) == (
        507,
        {"detail": "the organization stores as much as it may"},
    )
    assert validated.status_code == 200
    assert elsewhere.status_code == 201
    assert await stored_count(session) == 2


async def test_a_member_removed_while_the_invoice_is_validated_stores_nothing(
    session: AsyncSession, primer: Office
) -> None:
    """The upload and the validation outlast the permission check's transaction, so the
    membership is checked again where the invoice is stored."""
    scripted = Scripted()
    scripted.held = True

    async with application(session, using(scripted)) as api:
        upload = asyncio.create_task(submit(api, primer.as_client(), VALID))
        await asyncio.wait_for(scripted.entered.wait(), 5)
        await session.execute(delete(Membership).where(Membership.user_id == primer.client.id))
        scripted.release.set()
        response = await upload

    assert response.status_code == 401
    assert await stored_count(session) == 0


async def test_concurrent_uploads_cannot_take_an_organization_past_its_quota(
    committed_database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Adding up what is stored and storing one more happen under the organization's lock: two
    uploads with room for one store one, even when both add up before either stores."""
    async with committed_database.sessions() as setup:
        primer = Organization(name="Primer")
        ana = User(email="ana@primer.example", password_hash=NO_PASSWORD)
        setup.add_all([primer, ana])
        await setup.commit()
    _, detail = outcome(VALID, "srb", max_elements=20_000)
    validation = Validation.model_validate_json(detail)
    each = len(VALID) + len(validation.report.model_dump_json().encode())
    real = store.stored_bytes

    async def slowly(session: AsyncSession, organization_id: Any) -> int:
        counted = await real(session, organization_id)
        await asyncio.sleep(0.2)  # the other upload adds up meanwhile, if nothing stops it
        return counted

    monkeypatch.setattr(store, "stored_bytes", slowly)

    async def upload() -> str:
        async with committed_database.sessions() as session:
            try:
                await store.store(
                    session,
                    organization_id=primer.id,
                    submitted_by=ana.id,
                    profile="srb",
                    content=VALID,
                    validation=validation,
                    quota=each * 3 // 2,
                )
            except store.StorageFullError:
                return "full"
            return "stored"

    results = await asyncio.gather(upload(), upload())

    assert sorted(results) == ["full", "stored"]
