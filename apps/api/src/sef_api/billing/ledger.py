"""An organization's credits, where billing is on (ADR-0059): one is spent for each invoice it
stores, and none is spent anywhere else.

The account is opened the first time the organization spends or is given credits, with the
credits the settings start an organization with; until then its balance is that number, written
nowhere. Every change is an entry of the ledger, written in the transaction that changes the
balance, so that the balance is always the sum of the entries. A spend takes a credit only from
an account that has one, in one statement, so that two invoices stored at once cannot take an
organization below zero.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Final

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.models import CreditAccount, CreditEntry, CreditKind
from sef_api.settings import Settings

__all__ = [
    "MOST_ENTRIES",
    "NO_CREDITS",
    "CreditTerms",
    "NoCreditsError",
    "balance",
    "entries",
    "grant",
    "spend",
    "terms_for",
]

#: The most entries one page of the ledger holds.
MOST_ENTRIES: Final = 100
#: Why an invoice was not stored, in the routes' and the MCP tools' words.
NO_CREDITS: Final = (
    "the organization has no credit left to store an invoice: the operator grants more"
)


class NoCreditsError(Exception):
    """The organization has no credit left to spend."""


@dataclass(frozen=True)
class CreditTerms:
    """Billing as the settings set it: on, and the credits an organization starts with."""

    starting: int


def terms_for(settings: Settings) -> CreditTerms | None:
    """The terms the settings set; None where billing is off, and storing costs nothing."""
    if settings.billing == "off":
        return None
    return CreditTerms(starting=settings.starting_credits)


async def _open(session: AsyncSession, organization_id: uuid.UUID, terms: CreditTerms) -> None:
    """Open the organization's account with its starting credits, unless it has one."""
    opened = await session.scalar(
        insert(CreditAccount)
        .values(organization_id=organization_id, balance=terms.starting)
        .on_conflict_do_nothing(index_elements=[CreditAccount.organization_id])
        .returning(CreditAccount.organization_id)
    )
    if opened is not None and terms.starting > 0:
        session.add(
            CreditEntry(
                organization_id=organization_id,
                kind=CreditKind.OPENING,
                delta=terms.starting,
            )
        )


async def balance(session: AsyncSession, organization_id: uuid.UUID, terms: CreditTerms) -> int:
    """The credits the organization holds: its starting credits until it has an account."""
    held = await session.scalar(
        select(CreditAccount.balance).where(CreditAccount.organization_id == organization_id)
    )
    return terms.starting if held is None else held


async def spend(
    session: AsyncSession, organization_id: uuid.UUID, terms: CreditTerms, *, invoice_id: uuid.UUID
) -> int:
    """Spend one of the organization's credits on the invoice ``invoice_id``, and answer how
    many it has left; :class:`NoCreditsError` when it has none. The caller commits."""
    await _open(session, organization_id, terms)
    left = await session.scalar(
        update(CreditAccount)
        .where(CreditAccount.organization_id == organization_id, CreditAccount.balance > 0)
        .values(balance=CreditAccount.balance - 1)
        .returning(CreditAccount.balance)
        .execution_options(synchronize_session=False)
    )
    if left is None:
        raise NoCreditsError
    session.add(
        CreditEntry(
            organization_id=organization_id,
            kind=CreditKind.SPEND,
            delta=-1,
            invoice_id=invoice_id,
        )
    )
    return left


async def grant(
    session: AsyncSession, organization_id: uuid.UUID, terms: CreditTerms, *, count: int
) -> int:
    """Give the organization ``count`` more credits, and answer how many it then holds. The
    caller commits."""
    if count <= 0:
        raise ValueError("a grant gives at least one credit")
    await _open(session, organization_id, terms)
    held = await session.scalar(
        update(CreditAccount)
        .where(CreditAccount.organization_id == organization_id)
        .values(balance=CreditAccount.balance + count)
        .returning(CreditAccount.balance)
        .execution_options(synchronize_session=False)
    )
    assert held is not None  # the account was opened above
    session.add(CreditEntry(organization_id=organization_id, kind=CreditKind.GRANT, delta=count))
    return held


async def entries(
    session: AsyncSession, organization_id: uuid.UUID, *, limit: int = MOST_ENTRIES
) -> list[CreditEntry]:
    """The organization's latest ``limit`` entries, newest first."""
    found = await session.scalars(
        select(CreditEntry)
        .where(CreditEntry.organization_id == organization_id)
        .order_by(CreditEntry.number.desc())
        .limit(limit)
    )
    return list(found)
