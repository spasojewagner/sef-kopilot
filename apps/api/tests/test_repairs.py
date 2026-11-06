"""Repairs of stored invoices: proposed by a member or a machine client, applied to a copy of
the invoice in the validator's process, kept with what they did, and recorded in the audit
log without the invoice's content (ADR-0024)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from einvoice_core.patches import Patch
from sef_api.auth.dependencies import Principal
from sef_api.auth.permissions import Permission
from sef_api.db import get_session
from sef_api.invoices import store as invoice_store
from sef_api.invoices.validation import Patched, ProfileName, Validation, patched_outcome
from sef_api.invoices.validator import ThreadValidator, Validator
from sef_api.main import create_app
from sef_api.models import ApiKey, AuditEvent, Membership, Repair, Role, StoredInvoice
from sef_api.repairs import store

from .conftest import REPOSITORY_ROOT, settings_for
from .factories import Office, api_key, office, stored_invoice

SYNTHETIC = REPOSITORY_ROOT / "fixtures" / "invoices" / "synthetic"
MISTAKE = (SYNTHETIC / "mutations" / "srb-001-invoice-type-code.xml").read_bytes()
VALID = (SYNTHETIC / "srb-minimal-invoice.xml").read_bytes()
TYPE_CODE = {
    "xpath": "/ubl:Invoice/cbc:InvoiceTypeCode",
    "op": "replace",
    "value": "380",
    "reason": "SEF takes the invoice type codes 380, 381, 383 and 386 only",
}
PIB = {
    "xpath": "/ubl:Invoice/cac:AccountingSupplierParty/cac:Party/cbc:EndpointID",
    "op": "replace",
    "value": "100000024",
    "reason": "the check digit is wrong",
}
NOT_FOUND = {"detail": "no such invoice in this organization"}


@pytest.fixture
async def primer(session: AsyncSession) -> Office:
    return await office(session, "Primer Računovodstvo", "primer.example")


async def kept(session: AsyncSession, primer: Office, content: bytes = MISTAKE) -> StoredInvoice:
    return await stored_invoice(session, primer.organization, primer.client, content)


def path(invoice: StoredInvoice, *rest: object) -> str:
    return "/".join(["/invoices", str(invoice.id), "repairs", *map(str, rest)])


async def events(session: AsyncSession) -> list[AuditEvent]:
    return list(await session.scalars(select(AuditEvent).order_by(AuditEvent.at)))


async def test_a_repair_is_proposed_kept_and_audited_and_the_invoice_stays_as_it_was(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer)

    proposed = await api.post(
        path(invoice), json={"patches": [TYPE_CODE]}, headers=primer.as_client()
    )

    assert proposed.status_code == 201
    body = proposed.json()
    assert proposed.headers["Location"] == path(invoice, body["id"])
    assert {key: body[key] for key in ("status", "changed", "valid", "applied", "failed")} == {
        "status": "proposed",
        "changed": True,
        "valid": True,
        "applied": 1,
        "failed": 0,
    }
    assert (body["proposed_by"], body["proposed_with_key"]) == (str(primer.client.id), False)
    assert (body["decided_by"], body["decided_at"], body["needs_decision"]) == (None, None, 0)
    assert body["outcomes"] == [
        {"patch": TYPE_CODE, "status": "applied", "problem": None, "before": "393", "after": "380"}
    ]
    assert "+  <cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>" in body["diff"].splitlines()
    assert body["report"]["valid"] is True
    await session.refresh(invoice)
    assert invoice.sha256 == hashlib.sha256(MISTAKE).hexdigest()
    repair = await session.get(Repair, uuid.UUID(body["id"]))
    assert repair is not None
    assert repair.based_on == invoice.sha256
    expected = Patched.model_validate_json(
        patched_outcome(MISTAKE, "srb", [Patch.model_validate(TYPE_CODE)], max_elements=20_000)[1]
    )
    assert repair.patched_sha256 == hashlib.sha256(expected.document.encode()).hexdigest()
    (event,) = await events(session)
    assert (event.action, event.actor, event.key_id) == (
        "repair.proposed",
        primer.client.id,
        None,
    )
    assert (event.organization_id, event.invoice_id, event.repair_id) == (
        primer.organization.id,
        invoice.id,
        repair.id,
    )
    assert event.detail == {
        "based_on": repair.based_on,
        "patched_sha256": repair.patched_sha256,
        "changed": True,
        "valid": True,
        "patches": [
            {"xpath": "/ubl:Invoice/cbc:InvoiceTypeCode", "op": "replace", "status": "applied"}
        ],
    }


async def test_the_audit_log_keeps_no_value_and_no_reason(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer)
    note = {
        "xpath": "/ubl:Invoice/cbc:Note",
        "op": "replace",
        "value": "quoted-from-the-proposal",
        "reason": "reason-quoting-the-invoice",
    }

    proposed = await api.post(
        path(invoice), json={"patches": [TYPE_CODE, note]}, headers=primer.as_client()
    )

    assert proposed.status_code == 201
    (event,) = await events(session)
    written = json.dumps(event.detail)
    for quoted in ("quoted-from-the-proposal", "reason-quoting-the-invoice", "380", "393"):
        assert quoted not in written
    assert [patch["status"] for patch in event.detail["patches"]] == ["applied", "applied"]


async def test_a_patch_a_person_decides_is_kept_as_needing_their_decision(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer, VALID)

    proposed = await api.post(path(invoice), json={"patches": [PIB]}, headers=primer.as_owner())

    body = proposed.json()
    assert (proposed.status_code, body["changed"], body["diff"]) == (201, False, "")
    assert (body["applied"], body["needs_decision"]) == (0, 1)
    assert body["outcomes"][0]["problem"] == (
        "it touches a tax identifier (cbc:EndpointID): a person decides it"
    )


async def test_a_machine_client_proposes_a_repair_with_its_key(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer)
    key = await api_key(session, primer.organization, primer.client, Permission.INVOICES_SUBMIT)

    proposed = await api.post(path(invoice), json={"patches": [TYPE_CODE]}, headers=key.header())

    assert (proposed.status_code, proposed.json()["proposed_with_key"]) == (201, True)
    (event,) = await events(session)
    assert (event.actor, event.key_id) == (primer.client.id, key.row.id)


async def test_an_invoice_the_caller_may_not_see_takes_no_repair_and_shows_none(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    invoice = await stored_invoice(session, primer.organization, primer.accountant, MISTAKE)
    other = await office(session, "Drugi Ured", "drugi.example")
    stranger = await kept(session, other)

    for headers, target in ((primer.as_client(), invoice), (primer.as_owner(), stranger)):
        proposed = await api.post(path(target), json={"patches": [TYPE_CODE]}, headers=headers)
        listed = await api.get(path(target), headers=headers)
        one = await api.get(path(target, uuid.uuid4()), headers=headers)
        assert [proposed.status_code, listed.status_code, one.status_code] == [404] * 3
        assert proposed.json() == NOT_FOUND
    assert await events(session) == []


async def test_a_member_who_sees_every_invoice_may_propose_for_any(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer)

    proposed = await api.post(
        path(invoice), json={"patches": [TYPE_CODE]}, headers=primer.as_accountant()
    )

    assert (proposed.status_code, proposed.json()["proposed_by"]) == (
        201,
        str(primer.accountant.id),
    )


@pytest.mark.parametrize(
    "body",
    [
        {"patches": []},
        {"patches": [TYPE_CODE] * 101},
        {"patches": [TYPE_CODE | {"op": "move"}]},
        {"patches": [TYPE_CODE | {"value": " "}]},
        {"patches": [TYPE_CODE], "also": "this"},
        {"patch": TYPE_CODE},
    ],
)
async def test_what_is_not_a_list_of_patches_is_refused_before_anything_is_applied(
    api: AsyncClient, session: AsyncSession, primer: Office, body: dict[str, Any]
) -> None:
    invoice = await kept(session, primer)

    refused = await api.post(path(invoice), json=body, headers=primer.as_client())

    assert refused.status_code == 422
    assert await session.scalar(select(Repair.id)) is None


async def test_an_invoice_that_is_not_xml_takes_no_patch(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer, b"<Invoice>")

    refused = await api.post(
        path(invoice), json={"patches": [TYPE_CODE]}, headers=primer.as_client()
    )

    assert (refused.status_code, refused.json()) == (
        422,
        {"detail": "the invoice is not well-formed XML, so no patch applies to it"},
    )
    assert await events(session) == []


async def test_so_many_repairs_wait_for_a_decision_at_most(
    api: AsyncClient, session: AsyncSession, primer: Office, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store, "MAX_WAITING", 2)
    invoice = await kept(session, primer)

    answers = [
        await api.post(path(invoice), json={"patches": [TYPE_CODE]}, headers=primer.as_client())
        for _ in range(3)
    ]

    assert [answer.status_code for answer in answers] == [201, 201, 409]
    assert answers[2].json() == {
        "detail": "2 repairs of this invoice wait for a decision: decide on them first"
    }


async def test_repairs_are_listed_latest_first_and_read_one_by_one(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer)
    first = await api.post(path(invoice), json={"patches": [TYPE_CODE]}, headers=primer.as_client())
    # One transaction holds the whole test, so its repairs share a moment: the first is moved
    # back by a minute, as a request of a minute before would have stored it.
    await session.execute(
        update(Repair).values(created_at=Repair.created_at - timedelta(minutes=1))
    )
    second = await api.post(path(invoice), json={"patches": [PIB]}, headers=primer.as_client())

    listed = await api.get(path(invoice), headers=primer.as_client())
    one = await api.get(path(invoice, first.json()["id"]), headers=primer.as_client())

    assert listed.status_code == 200
    assert [repair["id"] for repair in listed.json()] == [second.json()["id"], first.json()["id"]]
    assert "report" not in listed.json()[0]
    assert "diff" not in listed.json()[0]
    moved = {"proposed_at"}  # moved back above
    assert one.status_code == 200
    assert {key: value for key, value in one.json().items() if key not in moved} == {
        key: value for key, value in first.json().items() if key not in moved
    }


async def test_a_repair_of_another_invoice_is_not_found_through_this_one(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    invoice, other = await kept(session, primer), await kept(session, primer, VALID)
    proposed = await api.post(path(other), json={"patches": [PIB]}, headers=primer.as_client())

    found = await api.get(path(invoice, proposed.json()["id"]), headers=primer.as_client())

    assert (found.status_code, found.json()) == (404, {"detail": "no such repair of this invoice"})


class Holding:
    """The test's validator, which holds each patch until it is let go."""

    problem = None

    def __init__(self) -> None:
        self.real = ThreadValidator(max_elements=20_000)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def start(self) -> None:
        pass

    async def validate(self, content: bytes, profile: ProfileName) -> Validation:
        return await self.real.validate(content, profile)

    async def patch(
        self, content: bytes, profile: ProfileName, patches: Sequence[Patch]
    ) -> Patched:
        self.entered.set()
        await self.release.wait()
        return await self.real.patch(content, profile, patches)

    async def stop(self) -> None:
        await self.real.stop()


@asynccontextmanager
async def serving(
    session: AsyncSession, validator: Validator | None = None, **variables: str
) -> AsyncIterator[AsyncClient]:
    app = create_app(settings_for(**variables))
    if validator is not None:
        app.state.validator = validator

    async def the_test_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = the_test_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    await app.state.database.engine.dispose()


async def test_proposing_a_repair_counts_as_a_validation(
    session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer)

    async with serving(session, SEF_VALIDATIONS_PER_MINUTE="1") as api:
        counted = await api.post(
            path(invoice), json={"patches": [TYPE_CODE]}, headers=primer.as_client()
        )
        held = await api.post(
            path(invoice), json={"patches": [TYPE_CODE]}, headers=primer.as_client()
        )

    assert (counted.status_code, held.status_code) == (201, 429)


async def test_a_repair_is_kept_only_for_the_document_its_patches_were_applied_to(
    session: AsyncSession, primer: Office, monkeypatch: pytest.MonkeyPatch
) -> None:
    invoice = await kept(session, primer)
    caller = Principal(primer.client.id, primer.organization.id, Role.CLIENT)
    patched = Patched.model_validate_json(
        patched_outcome(MISTAKE, "srb", [Patch.model_validate(TYPE_CODE)], max_elements=20_000)[1]
    )

    with pytest.raises(store.InvoiceChangedError):
        await store.propose(
            session, caller, invoice_id=invoice.id, based_on="0" * 64, patched=patched
        )
    gone = await store.propose(
        session, caller, invoice_id=uuid.uuid4(), based_on=invoice.sha256, patched=patched
    )
    monkeypatch.setattr(store, "MAX_WAITING", 0)  # as if another request had just proposed
    with pytest.raises(store.TooManyWaitingError):
        await store.propose(
            session, caller, invoice_id=invoice.id, based_on=invoice.sha256, patched=patched
        )

    assert gone is None
    assert await events(session) == []


@pytest.mark.parametrize(
    ("happened", "status", "detail"),
    [
        (
            store.TooManyWaitingError(),
            409,
            "10 repairs of this invoice wait for a decision: decide on them first",
        ),
        (
            store.InvoiceChangedError(),
            409,
            "the invoice changed while the patches were applied to it: propose them again",
        ),
        (None, 404, "no such invoice in this organization"),
    ],
)
async def test_what_happened_while_the_patches_were_applied_is_answered(
    api: AsyncClient,
    session: AsyncSession,
    primer: Office,
    monkeypatch: pytest.MonkeyPatch,
    happened: Exception | None,
    status: int,
    detail: str,
) -> None:
    invoice = await kept(session, primer)

    async def meanwhile(*_args: object, **_kwargs: object) -> None:
        if happened is not None:
            raise happened

    monkeypatch.setattr(store, "propose", meanwhile)

    answer = await api.post(
        path(invoice), json={"patches": [TYPE_CODE]}, headers=primer.as_client()
    )

    assert (answer.status_code, answer.json()) == (status, {"detail": detail})


async def test_a_member_removed_while_the_patches_are_applied_keeps_no_repair(
    session: AsyncSession, primer: Office
) -> None:
    """Applying the patches outlasts the permission check's transaction, so the membership is
    checked again where the repair is kept."""
    invoice = await kept(session, primer)
    holding = Holding()

    async with serving(session, holding) as api:
        proposing = asyncio.create_task(
            api.post(path(invoice), json={"patches": [TYPE_CODE]}, headers=primer.as_client())
        )
        await asyncio.wait_for(holding.entered.wait(), 5)
        await session.execute(delete(Membership).where(Membership.user_id == primer.client.id))
        holding.release.set()
        response = await proposing

    assert response.status_code == 401
    assert await session.scalar(select(Repair.id)) is None
    assert await events(session) == []


async def test_a_key_revoked_while_the_patches_are_applied_keeps_no_repair(
    session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer)
    key = await api_key(session, primer.organization, primer.client, Permission.INVOICES_SUBMIT)
    holding = Holding()

    async with serving(session, holding) as api:
        proposing = asyncio.create_task(
            api.post(path(invoice), json={"patches": [TYPE_CODE]}, headers=key.header())
        )
        await asyncio.wait_for(holding.entered.wait(), 5)
        await session.execute(
            update(ApiKey).where(ApiKey.id == key.row.id).values(revoked_at=func.now())
        )
        holding.release.set()
        response = await proposing

    assert response.status_code == 401
    assert await session.scalar(select(Repair.id)) is None


# --- deciding ------------------------------------------------------------------------------------

PERSON_ONLY = {"detail": "a person decides on a repair: sign in to decide, an API key cannot"}
LONG_NOTE = {
    "xpath": "/ubl:Invoice/cbc:Note[2]",
    "op": "add",
    "value": "N" * 1000,
    "reason": "a longer note",
}


async def proposed(
    api: AsyncClient, invoice: StoredInvoice, headers: dict[str, str], *patches: dict[str, Any]
) -> str:
    answer = await api.post(path(invoice), json={"patches": list(patches)}, headers=headers)
    assert answer.status_code == 201, answer.json()
    return str(answer.json()["id"])


async def test_a_person_approves_a_repair_and_the_invoice_becomes_the_patched_document(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer)
    repair_id = await proposed(api, invoice, primer.as_client(), TYPE_CODE)

    approved = await api.post(path(invoice, repair_id, "approval"), headers=primer.as_client())

    assert approved.status_code == 200
    body = approved.json()
    assert (body["status"], body["decided_by"]) == ("approved", str(primer.client.id))
    assert body["decided_at"] is not None
    await session.refresh(invoice)
    repair = await session.get(Repair, uuid.UUID(repair_id))
    assert repair is not None
    assert invoice.sha256 == repair.patched_sha256 != repair.based_on
    content = await session.scalar(
        select(StoredInvoice.content).where(StoredInvoice.id == invoice.id)
    )
    assert content is not None
    assert hashlib.sha256(content).hexdigest() == invoice.sha256
    assert b"<cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>" in content
    assert (invoice.valid, invoice.size, invoice.number) == (True, len(content), "RF-2026-000123")
    assert invoice.report["valid"] is True
    approval = (await events(session))[-1]
    assert (approval.action, approval.actor, approval.key_id) == (
        "repair.approved",
        primer.client.id,
        None,
    )
    assert approval.detail == {
        "based_on": repair.based_on,
        "patched_sha256": repair.patched_sha256,
        "valid": True,
        "superseded": [],
    }


async def test_an_api_key_proposes_but_only_a_person_decides(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer)
    key = await api_key(session, primer.organization, primer.client, Permission.INVOICES_SUBMIT)
    repair_id = await proposed(api, invoice, key.header(), TYPE_CODE)

    approval = await api.post(path(invoice, repair_id, "approval"), headers=key.header())
    rejection = await api.post(path(invoice, repair_id, "rejection"), headers=key.header())

    assert (approval.status_code, approval.json()) == (403, PERSON_ONLY)
    assert (rejection.status_code, rejection.json()) == (403, PERSON_ONLY)
    repair = await session.get(Repair, uuid.UUID(repair_id))
    assert repair is not None
    assert repair.status == "proposed"
    assert [event.action for event in await events(session)] == ["repair.proposed"]


async def test_approving_one_repair_supersedes_the_others_that_waited(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer)
    first = await proposed(api, invoice, primer.as_client(), TYPE_CODE)
    second = await proposed(api, invoice, primer.as_client(), LONG_NOTE)

    approved = await api.post(path(invoice, first, "approval"), headers=primer.as_client())
    too_late = await api.post(path(invoice, second, "approval"), headers=primer.as_client())

    assert approved.status_code == 200
    assert (too_late.status_code, too_late.json()) == (
        409,
        {"detail": "the repair is superseded: it waits for no decision"},
    )
    other = await session.get(Repair, uuid.UUID(second))
    assert other is not None
    await session.refresh(other)
    assert (other.status, other.decided_by) == ("superseded", None)
    assert other.decided_at is not None
    assert (await events(session))[-1].detail["superseded"] == [second]


async def test_a_repair_is_decided_once(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer)
    repair_id = await proposed(api, invoice, primer.as_client(), TYPE_CODE)
    await api.post(path(invoice, repair_id, "approval"), headers=primer.as_client())

    again = await api.post(path(invoice, repair_id, "approval"), headers=primer.as_client())
    rejected = await api.post(path(invoice, repair_id, "rejection"), headers=primer.as_client())

    for answer in (again, rejected):
        assert (answer.status_code, answer.json()) == (
            409,
            {"detail": "the repair is approved: it waits for no decision"},
        )


async def test_a_repair_that_changes_nothing_is_not_approved(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer, VALID)
    repair_id = await proposed(api, invoice, primer.as_client(), PIB)

    refused = await api.post(path(invoice, repair_id, "approval"), headers=primer.as_client())

    assert (refused.status_code, refused.json()) == (
        409,
        {"detail": "the repair changes nothing: there is nothing to approve"},
    )


async def test_a_person_rejects_a_repair_and_the_invoice_stays_as_it_was(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer)
    repair_id = await proposed(api, invoice, primer.as_client(), TYPE_CODE)

    rejected = await api.post(path(invoice, repair_id, "rejection"), headers=primer.as_owner())

    assert rejected.status_code == 200
    assert (rejected.json()["status"], rejected.json()["decided_by"]) == (
        "rejected",
        str(primer.owner.id),
    )
    await session.refresh(invoice)
    assert invoice.sha256 == hashlib.sha256(MISTAKE).hexdigest()
    rejection = (await events(session))[-1]
    assert (rejection.action, rejection.actor) == ("repair.rejected", primer.owner.id)
    assert rejection.detail == {"based_on": invoice.sha256}


async def test_a_repair_is_approved_only_onto_the_document_it_was_proposed_for(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer)
    repair_id = await proposed(api, invoice, primer.as_client(), TYPE_CODE)
    await session.execute(
        update(StoredInvoice)
        .where(StoredInvoice.id == invoice.id)
        .values(content=VALID, size=len(VALID), sha256=hashlib.sha256(VALID).hexdigest())
    )

    refused = await api.post(path(invoice, repair_id, "approval"), headers=primer.as_client())

    assert (refused.status_code, refused.json()) == (
        409,
        {"detail": "the invoice changed since the repair was proposed: propose it again"},
    )


async def test_patches_that_now_leave_another_document_are_not_approved(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer)
    repair_id = await proposed(api, invoice, primer.as_client(), TYPE_CODE)
    await session.execute(
        update(Repair).where(Repair.id == uuid.UUID(repair_id)).values(patched_sha256="0" * 64)
    )

    refused = await api.post(path(invoice, repair_id, "approval"), headers=primer.as_client())

    assert (refused.status_code, refused.json()) == (
        409,
        {
            "detail": "the patches no longer leave the document they left when they were "
            "proposed: propose them again"
        },
    )
    await session.refresh(invoice)
    assert invoice.sha256 == hashlib.sha256(MISTAKE).hexdigest()


async def test_an_approval_keeps_the_organization_within_its_quota(
    session: AsyncSession, primer: Office
) -> None:
    quota = 1024 * 1024
    invoice = await kept(session, primer)
    async with serving(session, SEF_MAX_STORED_BYTES=str(quota)) as api:
        repair_id = await proposed(api, invoice, primer.as_client(), LONG_NOTE)
        filler = quota - await invoice_store.stored_bytes(session, primer.organization.id) - 500
        await stored_invoice(
            session, primer.organization, primer.owner, b"x" * filler, report_size=1
        )
        refused = await api.post(path(invoice, repair_id, "approval"), headers=primer.as_client())

    assert (refused.status_code, refused.json()) == (
        507,
        {"detail": "the organization stores as much as it may"},
    )
    repair = await session.get(Repair, uuid.UUID(repair_id))
    assert repair is not None
    assert repair.status == "proposed"


async def test_a_repair_of_an_invoice_the_caller_may_not_see_is_not_decided(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    invoice = await stored_invoice(session, primer.organization, primer.accountant, MISTAKE)
    repair_id = await proposed(api, invoice, primer.as_accountant(), TYPE_CODE)

    for decision in ("approval", "rejection"):
        answer = await api.post(path(invoice, repair_id, decision), headers=primer.as_client())
        assert (answer.status_code, answer.json()) == (404, NOT_FOUND)
    for decision in ("approval", "rejection"):
        answer = await api.post(path(invoice, uuid.uuid4(), decision), headers=primer.as_owner())
        assert (answer.status_code, answer.json()) == (
            404,
            {"detail": "no such repair of this invoice"},
        )


async def test_a_member_removed_while_the_patches_are_applied_again_approves_nothing(
    session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer)
    holding = Holding()
    async with serving(session) as api:
        repair_id = await proposed(api, invoice, primer.as_client(), TYPE_CODE)
    async with serving(session, holding) as api:
        approving = asyncio.create_task(
            api.post(path(invoice, repair_id, "approval"), headers=primer.as_client())
        )
        await asyncio.wait_for(holding.entered.wait(), 5)
        await session.execute(delete(Membership).where(Membership.user_id == primer.client.id))
        holding.release.set()
        response = await approving

    assert response.status_code == 401
    await session.refresh(invoice)
    assert invoice.sha256 == hashlib.sha256(MISTAKE).hexdigest()


@pytest.mark.parametrize(
    ("happened", "status", "detail"),
    [
        (
            store.DecidedError("superseded"),
            409,
            "the repair is superseded: it waits for no decision",
        ),
        (
            store.InvoiceChangedError(),
            409,
            "the invoice changed since the repair was proposed: propose it again",
        ),
        (None, 404, "no such repair of this invoice"),
    ],
)
async def test_what_happened_while_the_patches_were_applied_again_is_answered(
    api: AsyncClient,
    session: AsyncSession,
    primer: Office,
    monkeypatch: pytest.MonkeyPatch,
    happened: Exception | None,
    status: int,
    detail: str,
) -> None:
    invoice = await kept(session, primer)
    repair_id = await proposed(api, invoice, primer.as_client(), TYPE_CODE)

    async def meanwhile(*_args: object, **_kwargs: object) -> None:
        if happened is not None:
            raise happened

    monkeypatch.setattr(store, "approve", meanwhile)

    answer = await api.post(path(invoice, repair_id, "approval"), headers=primer.as_client())

    assert (answer.status_code, answer.json()) == (status, {"detail": detail})


async def test_an_approval_applies_only_to_its_organizations_invoice_as_it_was_proposed(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer)
    repair_id = uuid.UUID(await proposed(api, invoice, primer.as_client(), TYPE_CODE))
    patched = Patched.model_validate_json(
        patched_outcome(MISTAKE, "srb", [Patch.model_validate(TYPE_CODE)], max_elements=20_000)[1]
    )
    other = await office(session, "Drugi Ured", "drugi.example")
    stranger = Principal(other.owner.id, other.organization.id, Role.OWNER)
    caller = Principal(primer.client.id, primer.organization.id, Role.CLIENT)
    quota = 1024 * 1024

    elsewhere = await store.approve(
        session, stranger, invoice_id=invoice.id, repair_id=repair_id, patched=patched, quota=quota
    )
    missing = await store.approve(
        session, caller, invoice_id=invoice.id, repair_id=uuid.uuid4(), patched=patched, quota=quota
    )
    await session.execute(
        update(StoredInvoice).where(StoredInvoice.id == invoice.id).values(sha256="0" * 64)
    )
    with pytest.raises(store.InvoiceChangedError):
        await store.approve(
            session,
            caller,
            invoice_id=invoice.id,
            repair_id=repair_id,
            patched=patched,
            quota=quota,
        )

    assert (elsewhere, missing) == (None, None)
    assert [event.action for event in await events(session)] == ["repair.proposed"]
    assert (
        await store.reject(session, caller, invoice_id=invoice.id, repair_id=uuid.uuid4()) is None
    )
