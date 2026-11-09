"""A stored invoice sent to SEF (ADR-0051): only when the validator passes it, with the
organization's key, once; SEF's answer kept, its words for the members alone; an answer that
never came asked for again with the same request id. SEF answers through a mock transport, as
its published OpenAPI document says it does. Who may call what, across organizations, is checked
in ``test_access_control.py``.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from einvoice_core.pipeline import ValidationReport
from sef_api.auth.dependencies import Principal
from sef_api.auth.permissions import Permission
from sef_api.db import Database, get_session
from sef_api.main import create_app
from sef_api.models import (
    SEF_STATUSES,
    AuditAction,
    AuditEvent,
    Role,
    SefSubmission,
    StoredInvoice,
    SubmissionState,
)
from sef_api.sef import submissions
from sef_api.sef.client import SefStatus
from sef_api.sef.keys import Keyring

from .conftest import REPOSITORY_ROOT, settings_for
from .factories import KEYRING, Office, api_key, office, sef_key, stored_invoice
from .test_sef_keys import NEXT_FERNET_KEY

SYNTHETIC = REPOSITORY_ROOT / "fixtures" / "invoices" / "synthetic"
VALID = (SYNTHETIC / "srb-minimal-invoice.xml").read_bytes()
#: The seller's PIB with a wrong check digit (SRB-009).
INVALID = (SYNTHETIC / "mutations" / "srb-009-pib-check-digit.xml").read_bytes()
KEY = "4711-4711-4711-4711"
SEF = "https://demoefaktura.mfin.gov.rs"
#: What SEF answers an import it accepts.
IMPORTED = {"invoiceId": 815, "purchaseInvoiceId": 0, "salesInvoiceId": 4711}


@dataclass
class FakeSef:
    """SEF's demo environment: what it was asked, and the answers it gives, in turn, the last one
    again once the others are given."""

    answers: list[Callable[[], httpx.Response]] = field(
        default_factory=lambda: [lambda: httpx.Response(200, json=IMPORTED)]
    )
    asked: list[httpx.Request] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(request)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        return answer()


@dataclass
class Served:
    api: AsyncClient
    app: FastAPI
    sef: FakeSef


@pytest.fixture
async def served(session: AsyncSession) -> AsyncIterator[Served]:
    """An application on the test's rolled-back session, whose SEF is :class:`FakeSef`."""
    app = create_app(settings_for())
    fake = FakeSef()
    await app.state.sef_http.aclose()
    app.state.sef_http = httpx.AsyncClient(transport=httpx.MockTransport(fake))

    async def the_test_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = the_test_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
        yield Served(api, app, fake)
    await app.state.sef_http.aclose()
    await app.state.database.engine.dispose()


@pytest.fixture
async def primer(session: AsyncSession) -> Office:
    created = await office(session, "Primer Računovodstvo", "primer.example")
    await sef_key(session, created.organization, KEY)
    return created


async def kept(session: AsyncSession, primer: Office, content: bytes = VALID) -> StoredInvoice:
    """An invoice Primer's client stored."""
    return await stored_invoice(session, primer.organization, primer.client, content)


async def submissions_kept(session: AsyncSession) -> list[SefSubmission]:
    return list(await session.scalars(select(SefSubmission).order_by(SefSubmission.sent_at)))


async def sent_events(session: AsyncSession) -> list[dict[str, Any]]:
    events = await session.scalars(
        select(AuditEvent).where(AuditEvent.action == AuditAction.SEF_INVOICE_SENT)
    )
    return [event.detail for event in events]


async def send(served: Served, invoice: StoredInvoice, primer: Office) -> httpx.Response:
    return await served.api.post(f"/invoices/{invoice.id}/sef", headers=primer.as_accountant())


# --- sent and imported -------------------------------------------------------------------------


async def test_a_valid_invoice_is_sent_with_the_organizations_key_and_sef_imports_it(
    served: Served, session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer)

    response = await send(served, invoice, primer)

    assert response.status_code == 201
    assert response.headers["Cache-Control"] == "no-store"
    body = response.json()
    assert {name: body[name] for name in ("state", "sales_invoice_id", "sef_invoice_id")} == {
        "state": "imported",
        "sales_invoice_id": 4711,
        "sef_invoice_id": 815,
    }
    assert (body["attempts"], body["refusal"], body["detail"], body["sef_status"]) == (
        1,
        None,
        None,
        None,
    )
    (asked,) = served.sef.asked
    assert str(asked.url).startswith(f"{SEF}/api/publicApi/sales-invoice/ubl?")
    assert asked.headers["ApiKey"] == KEY
    assert asked.content == VALID
    assert asked.url.params["requestId"] == body["id"]
    assert await sent_events(session) == [
        {
            "submission": body["id"],
            "sha256": hashlib.sha256(VALID).hexdigest(),
            "attempt": 1,
            "outcome": "imported",
        }
    ]


async def test_the_member_who_stored_it_sees_what_sef_answered(
    served: Served, session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer)
    sent = await send(served, invoice, primer)

    listed = await served.api.get(f"/invoices/{invoice.id}/sef", headers=primer.as_client())

    assert listed.status_code == 200
    assert listed.headers["Cache-Control"] == "no-store"
    assert listed.json() == [sent.json()]


async def test_an_invoice_sef_imported_is_not_sent_again(
    served: Served, session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer)
    await send(served, invoice, primer)

    again = await send(served, invoice, primer)

    assert (again.status_code, again.json()) == (
        409,
        {"detail": "SEF imported this invoice already", "reason": "sent"},
    )
    assert len(served.sef.asked) == 1


# --- not sent ----------------------------------------------------------------------------------


async def test_an_invoice_the_validator_does_not_pass_is_never_sent(
    served: Served, session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer, INVALID)

    response = await send(served, invoice, primer)

    assert (response.status_code, response.json()) == (
        409,
        {
            "detail": "the validator does not pass this invoice under SRB-CIUS: SRB-009",
            "reason": "invalid",
        },
    )
    assert served.sef.asked == []
    assert await submissions_kept(session) == []


async def test_without_the_organizations_key_nothing_is_sent(
    served: Served, session: AsyncSession
) -> None:
    keyless = await office(session, "Ogled", "ogled.example")
    invoice = await kept(session, keyless)

    response = await send(served, invoice, keyless)

    assert (response.status_code, response.json()["reason"]) == (409, "no-key")
    assert served.sef.asked == []
    assert await submissions_kept(session) == []


async def test_a_key_that_does_not_open_or_no_secret_sends_nothing(
    served: Served, session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer)
    served.app.state.sef_keys = Keyring((NEXT_FERNET_KEY,))
    unopened = await send(served, invoice, primer)
    served.app.state.sef_keys = None
    unkept = await send(served, invoice, primer)

    assert (unopened.status_code, unopened.json()["detail"]) == (
        503,
        "the organization's key to SEF cannot be opened with SEF_FERNET_KEY: an owner sets it "
        "again",
    )
    assert (unkept.status_code, unkept.json()["detail"]) == (
        503,
        "SEF keys cannot be kept on this server: SEF_FERNET_KEY is not set",
    )
    assert served.sef.asked == []
    assert await submissions_kept(session) == []


async def test_an_invoice_changed_while_it_was_validated_is_not_sent(
    served: Served, session: AsyncSession, primer: Office
) -> None:
    """A repair approved while the document was being validated: what was validated is not what
    would be sent."""
    invoice = await kept(session, primer)
    validator = served.app.state.validator
    validate = validator.validate

    async def while_a_repair_is_approved(content: bytes, profile: Any) -> Any:
        await session.execute(
            update(StoredInvoice).where(StoredInvoice.id == invoice.id).values(sha256="0" * 64)
        )
        return await validate(content, profile)

    validator.validate = while_a_repair_is_approved

    response = await send(served, invoice, primer)

    assert (response.status_code, response.json()["reason"]) == (409, "changed")
    assert served.sef.asked == []


async def test_a_member_who_may_not_send_sends_nothing(
    served: Served, session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer)

    response = await served.api.post(f"/invoices/{invoice.id}/sef", headers=primer.as_client())

    assert response.status_code == 403
    assert served.sef.asked == []


async def test_an_erps_key_that_holds_the_permission_sends_and_one_without_it_does_not(
    served: Served, session: AsyncSession, primer: Office
) -> None:
    """An accountant's keys: one may send, as their role does; the other, which may store and
    read every invoice, may not. The audit log names the key that sent."""
    invoice = await kept(session, primer)
    sending = await api_key(
        session,
        primer.organization,
        primer.accountant,
        Permission.INVOICES_MANAGE,
        Permission.INVOICES_SEND,
    )
    storing = await api_key(
        session,
        primer.organization,
        primer.accountant,
        Permission.INVOICES_SUBMIT,
        Permission.INVOICES_MANAGE,
    )

    refused = await served.api.post(f"/invoices/{invoice.id}/sef", headers=storing.header())
    sent = await served.api.post(f"/invoices/{invoice.id}/sef", headers=sending.header())

    assert (refused.status_code, refused.json()) == (
        403,
        {"detail": "requires the permission invoices:send"},
    )
    assert (sent.status_code, sent.json()["state"]) == (201, "imported")
    assert len(served.sef.asked) == 1
    event = await session.scalar(
        select(AuditEvent).where(AuditEvent.action == AuditAction.SEF_INVOICE_SENT)
    )
    assert event is not None
    assert (event.actor, event.key_id) == (primer.accountant.id, sending.row.id)


async def test_a_clients_key_sends_nothing_whatever_it_holds(
    served: Served, session: AsyncSession, primer: Office
) -> None:
    """What a key allows is decided by the role its member holds: a client's key may hold the
    permission in the table, and still sends nothing."""
    invoice = await kept(session, primer)
    key = await api_key(session, primer.organization, primer.client, Permission.INVOICES_SEND)

    response = await served.api.post(f"/invoices/{invoice.id}/sef", headers=key.header())

    assert response.status_code == 403
    assert served.sef.asked == []


# --- SEF's answers -----------------------------------------------------------------------------


async def test_an_answer_that_never_came_is_asked_for_again_with_the_same_request_id(
    served: Served, session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer)
    served.sef.answers = [
        lambda: httpx.Response(503),
        lambda: httpx.Response(503),
        lambda: httpx.Response(503),
        lambda: httpx.Response(200, json=IMPORTED),
    ]

    unanswered = await send(served, invoice, primer)
    answered = await send(served, invoice, primer)

    assert (unanswered.status_code, unanswered.json()["state"]) == (201, "unconfirmed")
    assert answered.json()["id"] == unanswered.json()["id"]
    assert (answered.json()["state"], answered.json()["attempts"]) == ("imported", 2)
    assert {request.url.params["requestId"] for request in served.sef.asked} == {
        unanswered.json()["id"]
    }
    assert [event["outcome"] for event in await sent_events(session)] == [
        "unavailable",
        "imported",
    ]


async def test_another_version_unconfirmed_holds_the_invoice_back(
    served: Served, session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer)
    session.add(
        SefSubmission(
            organization_id=primer.organization.id,
            invoice_id=invoice.id,
            sha256="1" * 64,
            state=SubmissionState.UNCONFIRMED,
        )
    )
    await session.flush()

    response = await send(served, invoice, primer)

    assert (response.status_code, response.json()["reason"]) == (409, "unconfirmed")
    assert served.sef.asked == []


async def test_a_refusal_keeps_sefs_words_and_the_invoice_may_be_sent_again(
    served: Served, session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer)
    words = '{"Message": "Faktura RF-2026-000123 već postoji"}'
    served.sef.answers = [
        lambda: httpx.Response(400, text=words),
        lambda: httpx.Response(200, json=IMPORTED),
    ]

    refused = await send(served, invoice, primer)
    imported = await send(served, invoice, primer)
    listed = await served.api.get(f"/invoices/{invoice.id}/sef", headers=primer.as_owner())

    assert (refused.json()["state"], refused.json()["refusal"], refused.json()["detail"]) == (
        "refused",
        "invoice",
        words,
    )
    assert imported.json()["state"] == "imported"
    assert imported.json()["id"] != refused.json()["id"]
    assert [item["state"] for item in listed.json()] == ["imported", "refused"]


@pytest.mark.parametrize("status", [401, 403])
async def test_a_key_sef_refuses_is_said_so(
    served: Served, session: AsyncSession, primer: Office, status: int
) -> None:
    invoice = await kept(session, primer)
    served.sef.answers = [lambda: httpx.Response(status, text="Invalid ApiKey")]

    response = await send(served, invoice, primer)

    assert (response.json()["state"], response.json()["refusal"], response.json()["detail"]) == (
        "refused",
        "key",
        None,
    )


async def test_nothing_sef_wrote_and_no_key_is_logged(
    served: Served, session: AsyncSession, primer: Office, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    invoice = await kept(session, primer)
    served.sef.answers = [lambda: httpx.Response(400, text="Faktura RF-2026-000123 odbijena")]

    response = await send(served, invoice, primer)

    assert "RF-2026-000123" not in caplog.text
    assert KEY not in caplog.text
    events = [
        getattr(record, "fields", {})
        for record in caplog.records
        if getattr(record, "event", None) == "sef.invoice-sent"
    ]
    assert events == [
        {
            "organization": str(primer.organization.id),
            "user": str(primer.accountant.id),
            "invoice": str(invoice.id),
            "submission": response.json()["id"],
            "outcome": "refused",
        }
    ]


# --- the records -------------------------------------------------------------------------------


async def test_the_submissions_go_with_their_invoice(
    served: Served, session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer)
    await send(served, invoice, primer)

    deleted = await served.api.delete(f"/invoices/{invoice.id}", headers=primer.as_client())

    assert deleted.status_code == 204
    assert await session.scalar(select(func.count()).select_from(SefSubmission)) == 0


async def test_an_imported_submission_has_its_id_and_a_refused_one_its_reason(
    session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer)
    session.add(
        SefSubmission(
            organization_id=primer.organization.id,
            invoice_id=invoice.id,
            sha256="1" * 64,
            state=SubmissionState.IMPORTED,
        )
    )

    with pytest.raises(IntegrityError, match="ck_sef_submissions_imported_with_its_id"):
        await session.flush()


def test_the_statuses_the_table_knows_are_the_ones_sef_names() -> None:
    assert set(SEF_STATUSES) == {status.value for status in SefStatus}


async def test_an_unknown_invoice_has_nothing_to_show(served: Served, primer: Office) -> None:
    response = await served.api.get(f"/invoices/{uuid.uuid4()}/sef", headers=primer.as_owner())

    assert (response.status_code, response.json()) == (
        404,
        {"detail": "no such invoice in this organization"},
    )


# --- in production's order -----------------------------------------------------------------------


async def test_a_member_who_lost_the_permission_meanwhile_sends_nothing(
    served: Served, session: AsyncSession, primer: Office
) -> None:
    """The token says accountant; the membership, changed since, says client: the check under
    the invoice's lock refuses, before SEF is asked."""
    invoice = await kept(session, primer)
    report = ValidationReport(profile="srb", valid=True, violations=(), layers=())
    sending = submissions.sendable(invoice, VALID, report)
    demoted = Principal(primer.client.id, primer.organization.id, Role.ACCOUNTANT)

    with pytest.raises(HTTPException) as raised:
        await submissions.send(
            session, demoted, sending, keyring=KEYRING, http=served.app.state.sef_http, base_url=SEF
        )

    assert raised.value.status_code == 403
    assert served.sef.asked == []
    assert await submissions_kept(session) == []


async def test_the_submission_is_committed_before_sef_is_asked(
    committed_database: Database, database_url: str
) -> None:
    """Were the process to stop while SEF answers, the request id would be there to ask again."""
    async with committed_database.sessions() as session:
        primer = await office(session, "Primer Računovodstvo", "primer.example")
        await sef_key(session, primer.organization, KEY)
        invoice = await stored_invoice(session, primer.organization, primer.client, VALID)
        await session.commit()
    seen: list[list[tuple[uuid.UUID, str]]] = []

    async def sef(_: httpx.Request) -> httpx.Response:
        async with committed_database.sessions() as session:
            rows = await session.execute(select(SefSubmission.id, SefSubmission.state))
            seen.append([(row.id, row.state) for row in rows])
        return httpx.Response(200, json=IMPORTED)

    app = create_app(settings_for(database_url))
    await app.state.sef_http.aclose()
    app.state.sef_http = httpx.AsyncClient(transport=httpx.MockTransport(sef))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
        response = await api.post(f"/invoices/{invoice.id}/sef", headers=primer.as_accountant())
    await app.state.sef_http.aclose()
    await app.state.database.engine.dispose()

    assert response.status_code == 201
    assert seen == [[(uuid.UUID(response.json()["id"]), "unconfirmed")]]
