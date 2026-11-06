"""Repairs as the database keeps them (ADR-0024).

A repair is proposed for an invoice as it was when its patches were applied to it:
``based_on`` is that document's digest. At most :data:`MAX_WAITING` repairs of one invoice
wait for a decision. Proposing locks the invoice's row, so that the count holds when requests
arrive together, and so that the invoice cannot change between the check that it is the
document the patches were applied to and the insert. Each proposal is committed with its audit
event.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api import audit
from sef_api.auth.dependencies import Principal
from sef_api.invoices.validation import Patched
from sef_api.models import AuditAction, Repair, RepairStatus, StoredInvoice

__all__ = [
    "MAX_LISTED",
    "MAX_WAITING",
    "InvoiceChangedError",
    "TooManyWaitingError",
    "find",
    "propose",
    "repairs_of",
    "waiting",
]

#: The most repairs of one invoice that wait for a decision at once.
MAX_WAITING: Final = 10
#: The most repairs of one invoice a list shows: the latest ones.
MAX_LISTED: Final = 100


class TooManyWaitingError(Exception):
    """As many repairs of the invoice as allowed wait for a decision."""


class InvoiceChangedError(Exception):
    """The invoice is no longer the document the patches were applied to."""


async def waiting(session: AsyncSession, invoice_id: uuid.UUID) -> int:
    """How many repairs of the invoice wait for a decision."""
    count = await session.scalar(
        select(func.count())
        .select_from(Repair)
        .where(Repair.invoice_id == invoice_id, Repair.status == RepairStatus.PROPOSED)
    )
    return int(count or 0)


def _detail(based_on: str, patched_sha256: str, patched: Patched) -> dict[str, Any]:
    """What the audit log keeps of a proposal: digests, the verdict, and each patch's place,
    operation and outcome; never a value or a reason."""
    return {
        "based_on": based_on,
        "patched_sha256": patched_sha256,
        "changed": patched.changed,
        "valid": patched.validation.report.valid,
        "patches": [
            {"xpath": outcome.patch.xpath, "op": outcome.patch.op, "status": outcome.status}
            for outcome in patched.outcomes
        ],
    }


async def propose(
    session: AsyncSession,
    caller: Principal,
    *,
    invoice_id: uuid.UUID,
    based_on: str,
    patched: Patched,
) -> Repair | None:
    """Keep the repair ``patched`` describes, of the invoice whose document had the digest
    ``based_on``, with its audit event, and commit. None when the invoice is gone;
    :class:`InvoiceChangedError` when it has another document now, and
    :class:`TooManyWaitingError` when as many of its repairs as allowed wait already."""
    current = await session.scalar(
        select(StoredInvoice.sha256).where(StoredInvoice.id == invoice_id).with_for_update()
    )
    if current is None:
        return None
    if current != based_on:
        raise InvoiceChangedError
    if await waiting(session, invoice_id) >= MAX_WAITING:
        raise TooManyWaitingError
    patched_sha256 = hashlib.sha256(patched.document.encode()).hexdigest()
    repair = Repair(
        organization_id=caller.organization_id,
        invoice_id=invoice_id,
        proposed_by=caller.user_id,
        key_id=None if caller.key is None else caller.key.key_id,
        based_on=based_on,
        patched_sha256=patched_sha256,
        outcomes=[outcome.model_dump(mode="json") for outcome in patched.outcomes],
        changed=patched.changed,
        valid=patched.validation.report.valid,
        report=patched.validation.report.model_dump(mode="json"),
        diff=patched.diff,
    )
    session.add(repair)
    await session.flush()
    audit.record(
        session,
        caller,
        AuditAction.REPAIR_PROPOSED,
        invoice_id=invoice_id,
        repair_id=repair.id,
        detail=_detail(based_on, patched_sha256, patched),
    )
    await session.commit()
    return repair


async def repairs_of(session: AsyncSession, invoice_id: uuid.UUID) -> list[Repair]:
    """The repairs of the invoice, the latest first, at most :data:`MAX_LISTED`."""
    found = await session.scalars(
        select(Repair)
        .where(Repair.invoice_id == invoice_id)
        .order_by(Repair.created_at.desc(), Repair.id.desc())
        .limit(MAX_LISTED)
    )
    return list(found)


async def find(session: AsyncSession, invoice_id: uuid.UUID, repair_id: uuid.UUID) -> Repair | None:
    """The repair ``repair_id`` of the invoice, or None."""
    return await session.scalar(
        select(Repair).where(Repair.invoice_id == invoice_id, Repair.id == repair_id)
    )
