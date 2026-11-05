"""Stored invoices: an organization keeps the invoices its members submit, each with the
validator's latest report on it, within a storage quota (ADR-0016).

What an organization stores is counted in bytes, its documents and their reports together: a
small invoice that breaks many rules has a report many times its size. Adding up what is
stored and storing one more, or replacing a report with a larger one (ADR-0019), happen under
a lock on the organization's stored invoices, so that no two of them can take it past its
quota.

Every read is within a :class:`Scope`: the organization, and for a member who may not see
every invoice of it, only the ones they submitted. An invoice outside the scope does not
exist for the caller. Lists are newest first and come in pages, each continued from a
:data:`Cursor` that names the last invoice of the page before.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal

from sqlalchemy import ColumnElement, Select, delete, func, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.invoices.validation import InvoiceSummary, ProfileName, Validation
from sef_api.locks import lock_invoice_storage
from sef_api.models import StoredInvoice

__all__ = [
    "MAX_PAGE",
    "Cursor",
    "InvalidCursorError",
    "Page",
    "Scope",
    "StorageFullError",
    "content_of",
    "cursor_after",
    "find",
    "forget",
    "page_of",
    "replace_report",
    "store",
    "stored_bytes",
]

#: The most invoices one page lists.
MAX_PAGE: Final = 100

#: Where a list continues: after the invoice stored at this time with this id.
Cursor = tuple[datetime, uuid.UUID]


class StorageFullError(Exception):
    """Storing the invoice would take the organization past its quota."""


class InvalidCursorError(Exception):
    """The text is not a cursor this API gave."""


@dataclass(frozen=True)
class Scope:
    """The invoices a caller may see: the organization's, or only the ones ``submitted_by``."""

    organization_id: uuid.UUID
    submitted_by: uuid.UUID | None = None

    def holds(self) -> ColumnElement[bool]:
        own = StoredInvoice.organization_id == self.organization_id
        if self.submitted_by is None:
            return own
        return own & (StoredInvoice.submitted_by == self.submitted_by)


@dataclass(frozen=True)
class Page:
    invoices: list[StoredInvoice]
    next: str | None


#: The columns an invoice is listed by, from what the validator read.
_LISTED: Final = (
    "document_type",
    "number",
    "issue_date",
    "currency",
    "seller",
    "buyer",
    "payable_amount",
)


def _listing(summary: InvoiceSummary | None) -> dict[str, Any]:
    """The listing columns: what the validator read, or none of it."""
    if summary is None:
        return dict.fromkeys(_LISTED)
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


async def replace_report(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    invoice_id: uuid.UUID,
    validation: Validation,
    quota: int,
) -> Literal["replaced", "kept", "gone"]:
    """Make ``validation`` the latest report on the organization's invoice, without committing:
    the caller commits it with whatever else belongs to the change, and the lock on the
    organization's stored invoices is held until then.

    ``"kept"`` when the new report is larger than the old one and the organization would then
    store more than ``quota`` bytes: the invoice keeps the report it has. ``"gone"`` when the
    organization has no such invoice, as when it was deleted meanwhile.
    """
    await lock_invoice_storage(session, organization_id)
    old = await session.scalar(
        select(StoredInvoice.report_size)
        .where(StoredInvoice.organization_id == organization_id, StoredInvoice.id == invoice_id)
        .with_for_update()
    )
    if old is None:
        return "gone"
    size = len(validation.report.model_dump_json().encode())
    if size > old and await stored_bytes(session, organization_id) - old + size > quota:
        return "kept"
    await session.execute(
        update(StoredInvoice)
        .where(StoredInvoice.id == invoice_id)
        .values(
            valid=validation.report.valid,
            report=validation.report.model_dump(mode="json"),
            report_size=size,
            validated_at=func.now(),
            **_listing(validation.summary),
        )
    )
    return "replaced"


def cursor_after(invoice: StoredInvoice) -> str:
    """The cursor that continues a list after ``invoice``: opaque, and safe in a URL."""
    text = f"{invoice.created_at.isoformat()} {invoice.id}"
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def _position(cursor: str) -> Cursor:
    try:
        text = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        moment, identifier = text.split(" ")
        position = (datetime.fromisoformat(moment), uuid.UUID(identifier))
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise InvalidCursorError from None
    if position[0].tzinfo is None:
        raise InvalidCursorError
    return position


def _scoped(scope: Scope) -> Select[StoredInvoice]:
    return select(StoredInvoice).where(scope.holds())


async def page_of(
    session: AsyncSession, scope: Scope, *, limit: int, after: str | None = None
) -> Page:
    """The newest ``limit`` invoices in ``scope``, or the next ones ``after`` a cursor; raises
    :class:`InvalidCursorError` for a cursor this API did not give."""
    query = _scoped(scope)
    if after is not None:
        moment, identifier = _position(after)
        query = query.where(
            tuple_(StoredInvoice.created_at, StoredInvoice.id) < tuple_(moment, identifier)
        )
    query = query.order_by(StoredInvoice.created_at.desc(), StoredInvoice.id.desc())
    invoices = list((await session.scalars(query.limit(limit + 1))).all())
    more = len(invoices) > limit
    invoices = invoices[:limit]
    return Page(invoices, cursor_after(invoices[-1]) if more else None)


async def find(session: AsyncSession, scope: Scope, invoice_id: uuid.UUID) -> StoredInvoice | None:
    """The invoice with ``invoice_id`` in ``scope``, without its document."""
    return await session.scalar(_scoped(scope).where(StoredInvoice.id == invoice_id))


async def content_of(session: AsyncSession, scope: Scope, invoice_id: uuid.UUID) -> bytes | None:
    """The document of the invoice with ``invoice_id`` in ``scope``, byte for byte."""
    return await session.scalar(
        select(StoredInvoice.content).where(scope.holds(), StoredInvoice.id == invoice_id)
    )


async def forget(session: AsyncSession, scope: Scope, invoice_id: uuid.UUID) -> bool:
    """Delete the invoice with ``invoice_id`` in ``scope``, its document and its report, and
    commit; False when there is no such invoice."""
    deleted = await session.scalar(
        delete(StoredInvoice)
        .where(scope.holds(), StoredInvoice.id == invoice_id)
        .returning(StoredInvoice.id)
    )
    await session.commit()
    return deleted is not None
