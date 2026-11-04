"""Stored invoices: an organization keeps the invoices its members submit, each with the
validator's report on it, within a storage quota (ADR-0016).

What an organization stores is counted in bytes, its documents and their reports together: a
small invoice that breaks many rules has a report many times its size. Adding up what is
stored and storing one more happen under a lock on the organization's stored invoices, so
that concurrent uploads cannot take it past its quota.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.invoices.validation import InvoiceSummary, ProfileName, Validation
from sef_api.locks import lock_invoice_storage
from sef_api.models import StoredInvoice

__all__ = ["StorageFullError", "store", "stored_bytes"]


class StorageFullError(Exception):
    """Storing the invoice would take the organization past its quota."""


def _listing(summary: InvoiceSummary | None) -> dict[str, Any]:
    if summary is None:
        return {}
    return {
        "document_type": summary.document_type,
        "number": summary.number,
        "issue_date": summary.issue_date,
        "currency": summary.currency,
        "seller": summary.seller,
        "buyer": summary.buyer,
        "payable_amount": summary.payable_amount,
    }


async def stored_bytes(session: AsyncSession, organization_id: uuid.UUID) -> int:
    """What the organization stores: the bytes of its documents and of their reports."""
    total = await session.scalar(
        select(func.coalesce(func.sum(StoredInvoice.size + StoredInvoice.report_size), 0)).where(
            StoredInvoice.organization_id == organization_id
        )
    )
    return int(total or 0)


async def store(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    submitted_by: uuid.UUID,
    profile: ProfileName,
    content: bytes,
    validation: Validation,
    quota: int,
) -> StoredInvoice:
    """Store ``content`` with its validation and commit, or raise :class:`StorageFullError`
    when the organization would then store more than ``quota`` bytes; the caller's session
    then ends the transaction, and with it the lock."""
    invoice = StoredInvoice(
        organization_id=organization_id,
        submitted_by=submitted_by,
        profile=profile,
        valid=validation.report.valid,
        report=validation.report.model_dump(mode="json"),
        report_size=len(validation.report.model_dump_json().encode()),
        content=content,
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        **_listing(validation.summary),
    )
    await lock_invoice_storage(session, organization_id)
    if await stored_bytes(session, organization_id) + invoice.size + invoice.report_size > quota:
        raise StorageFullError
    session.add(invoice)
    await session.commit()
    return invoice
