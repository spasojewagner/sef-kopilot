"""A stored invoice sent to SEF in its organization's name, and what SEF answered (ADR-0051).

Nothing leaves without a green validator: the document is validated again under SRB-CIUS just
before it is sent, and sent only when the report has no violation that makes it invalid, byte
for byte as validated (its digest is checked again under the invoice's lock). An invoice is
sent with its organization's key, which an owner set (ADR-0050).

The submission is committed, unconfirmed, before SEF is asked, with the id that goes to SEF as
the ``requestId``; so a request whose answer never came is asked again with the same id, and SEF
imports the invoice once. SEF's answer then makes it imported, with SEF's ids, or refused, with
SEF's words; an answer that never came leaves it unconfirmed, and sending the invoice again asks
SEF again. An invoice that SEF imported is not sent again.

The audit log records each sending with the document's digest and what SEF answered; a security
event says who sent which invoice and how it ended. Neither holds what SEF wrote, which may
quote the invoice.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal

import httpx
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from einvoice_core.pipeline import ValidationReport
from einvoice_core.violations import Severity
from sef_api import audit
from sef_api.auth.dependencies import Principal, check_again
from sef_api.auth.permissions import Permission
from sef_api.logs import security_event
from sef_api.models import (
    AuditAction,
    SefKey,
    SefSubmission,
    StoredInvoice,
    SubmissionState,
)
from sef_api.sef.client import SefClient, SefError
from sef_api.sef.keys import Keyring, UnreadableKeyError

__all__ = [
    "NotSendableError",
    "Reason",
    "SefUnusableError",
    "Sending",
    "send",
    "sendable",
    "submissions_of",
]

#: The profile SEF holds an invoice to.
PROFILE: Final = "srb"
#: The most rules a refusal of an invalid invoice names.
MAX_NAMED: Final = 10

Reason = Literal["invalid", "no-key", "sent", "unconfirmed", "changed"]


class NotSendableError(Exception):
    """An invoice that is not sent, and why: ``invalid``, the validator does not pass it under
    SRB-CIUS; ``no-key``, the organization has no key to SEF; ``sent``, SEF imported it already;
    ``unconfirmed``, another version of it was sent, and SEF's answer is not yet read;
    ``changed``, it changed while it was being validated."""

    def __init__(self, reason: Reason, detail: str) -> None:
        super().__init__(detail)
        self.reason: Reason = reason
        self.detail = detail


class SefUnusableError(Exception):
    """SEF cannot be asked: the organization's key does not open (``SEF_FERNET_KEY`` changed),
    or no key can be kept on this server. The message says which, for the person."""


@dataclass(frozen=True)
class Sending:
    """An invoice about to be sent: its document and the digest of it that was validated."""

    invoice: StoredInvoice
    document: bytes
    sha256: str


def sendable(invoice: StoredInvoice, document: bytes, report: ValidationReport) -> Sending:
    """``document``, the invoice's, which ``report`` judged under SRB-CIUS, if it may be sent:
    :class:`NotSendableError` when the report finds it invalid."""
    if not report.valid:
        blocking = sorted(
            {
                violation.rule_id
                for violation in report.violations
                if violation.severity is Severity.FATAL
            }
        )
        shown = ", ".join(blocking[:MAX_NAMED]) + (" and more" if len(blocking) > MAX_NAMED else "")
        raise NotSendableError(
            "invalid", f"the validator does not pass this invoice under SRB-CIUS: {shown}"
        )
    return Sending(invoice, document, hashlib.sha256(document).hexdigest())


async def send(
    session: AsyncSession,
    caller: Principal,
    sending: Sending,
    *,
    keyring: Keyring | None,
    http: httpx.AsyncClient,
    base_url: str,
) -> SefSubmission:
    """Send ``sending`` to SEF with the organization's key and keep what SEF answered; the
    submission, committed. :class:`NotSendableError` or :class:`SefUnusableError` before
    anything is sent; 403 for a caller who no longer holds the permission."""
    submission, api_key = await _begin(session, caller, sending, keyring)
    client = SefClient(base_url, api_key, client=http)
    outcome: str
    try:
        imported = await client.send(sending.document, submission.id)
    except SefError as error:
        if error.kind in {"refused", "unauthorized"}:
            submission.state = SubmissionState.REFUSED
            submission.refusal = "invoice" if error.kind == "refused" else "key"
            submission.detail = error.detail
            submission.answered_at = datetime.now(UTC)
        outcome = error.kind
    else:
        submission.state = SubmissionState.IMPORTED
        submission.sales_invoice_id = imported.sales_invoice_id
        submission.sef_invoice_id = imported.invoice_id
        submission.answered_at = datetime.now(UTC)
        outcome = "imported"
    audit.record(
        session,
        caller,
        AuditAction.SEF_INVOICE_SENT,
        invoice_id=sending.invoice.id,
        detail={
            "submission": str(submission.id),
            "sha256": sending.sha256,
            "attempt": submission.attempts,
            "outcome": outcome,
        },
    )
    await session.commit()
    security_event(
        "sef.invoice-sent",
        organization=str(caller.organization_id),
        user=str(caller.user_id),
        invoice=str(sending.invoice.id),
        submission=str(submission.id),
        outcome=outcome,
    )
    return submission


async def _begin(
    session: AsyncSession, caller: Principal, sending: Sending, keyring: Keyring | None
) -> tuple[SefSubmission, SecretStr]:
    """Under the invoice's lock: check again that it may be sent as validated, open the key,
    and commit the submission that is about to be sent, a new one or the unconfirmed one again."""
    locked = await session.scalar(
        select(StoredInvoice.sha256).where(StoredInvoice.id == sending.invoice.id).with_for_update()
    )
    if locked != sending.sha256:
        raise NotSendableError(
            "changed", "the invoice changed while it was being validated: send it again"
        )
    permitted = await check_again(session, caller, Permission.INVOICES_SEND)
    live = await session.scalar(
        select(SefSubmission).where(
            SefSubmission.invoice_id == sending.invoice.id,
            SefSubmission.state.in_([SubmissionState.UNCONFIRMED, SubmissionState.IMPORTED]),
        )
    )
    if live is not None and live.state == SubmissionState.IMPORTED:
        raise NotSendableError("sent", "SEF imported this invoice already")
    if live is not None and live.sha256 != sending.sha256:
        raise NotSendableError(
            "unconfirmed",
            "another version of this invoice was sent, and SEF's answer is not yet read",
        )
    if keyring is None:
        raise SefUnusableError("SEF keys cannot be kept on this server: SEF_FERNET_KEY is not set")
    token = await session.scalar(
        select(SefKey.token).where(SefKey.organization_id == permitted.organization_id)
    )
    if token is None:
        raise NotSendableError(
            "no-key", "the organization has no key to SEF: an owner sets it first"
        )
    try:
        api_key = keyring.open(permitted.organization_id, token)
    except UnreadableKeyError:
        raise SefUnusableError(
            "the organization's key to SEF cannot be opened with SEF_FERNET_KEY: an owner sets "
            "it again"
        ) from None
    if live is None:
        submission = SefSubmission(
            organization_id=permitted.organization_id,
            invoice_id=sending.invoice.id,
            submitted_by=permitted.user_id,
            sha256=sending.sha256,
            state=SubmissionState.UNCONFIRMED,
            # The moment it is sent, not its transaction's: two sendings of one transaction keep
            # their order.
            sent_at=datetime.now(UTC),
        )
        session.add(submission)
    else:
        submission = live
        submission.attempts += 1
    await session.commit()
    return submission, api_key


async def submissions_of(session: AsyncSession, invoice_id: uuid.UUID) -> list[SefSubmission]:
    """The submissions of the invoice, the newest first."""
    found = await session.scalars(
        select(SefSubmission)
        .where(SefSubmission.invoice_id == invoice_id)
        .order_by(SefSubmission.sent_at.desc(), SefSubmission.id)
    )
    return list(found)
