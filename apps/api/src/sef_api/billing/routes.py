"""``/billing``: the credits of the caller's organization, where billing is on (ADR-0059).

Whoever may store invoices, and so spend credits, a person or an API key, sees how many are
left; the owner sees the ledger, every change of them. Where billing is off, storing costs
nothing and the server says so.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.auth.dependencies import Principal, require
from sef_api.auth.permissions import Permission
from sef_api.billing import ledger
from sef_api.db import get_session

router = APIRouter(prefix="/billing", tags=["billing"])

Session = Annotated[AsyncSession, Depends(get_session)]
CanSubmit = Annotated[Principal, Depends(require(Permission.INVOICES_SUBMIT))]
CanManage = Annotated[Principal, Depends(require(Permission.ORGANIZATION_MANAGE))]


class Billing(BaseModel):
    enabled: bool = Field(
        description="Whether storing an invoice costs a credit on this server; when not, every "
        "other field is null."
    )
    balance: int | None = Field(description="The credits the organization holds.")
    starting: int | None = Field(description="The credits an organization starts with.")
    per_invoice: int | None = Field(description="The credits one stored invoice costs.")


class CreditEntryOut(BaseModel):
    id: uuid.UUID
    at: datetime
    kind: Literal["opening", "spend", "grant"] = Field(
        description="`opening`, the starting credits; `spend`, a stored invoice; `grant`, "
        "credits the operator gave."
    )
    delta: int = Field(description="The change of the balance: negative for a spend.")
    invoice_id: uuid.UUID | None = Field(
        description="The stored invoice a spend paid for, which may since have been deleted."
    )


def _terms(request: Request) -> ledger.CreditTerms | None:
    return cast(ledger.CreditTerms | None, request.app.state.credit_terms)


@router.get(
    "",
    summary="See the organization's credits",
    description=(
        "Whether storing an invoice costs a credit on this server, and if so how many the "
        "organization holds. Anyone who may store invoices sees it, an API key that may too."
    ),
)
async def get_billing(request: Request, caller: CanSubmit, session: Session) -> Billing:
    terms = _terms(request)
    if terms is None:
        return Billing(enabled=False, balance=None, starting=None, per_invoice=None)
    held = await ledger.balance(session, caller.organization_id, terms)
    return Billing(enabled=True, balance=held, starting=terms.starting, per_invoice=1)


@router.get(
    "/entries",
    summary="List the changes of the organization's credits",
    description=(
        "The organization's ledger, newest first: its starting credits, each stored invoice's "
        "spend and each grant. The owner sees it; it is empty where billing is off or before "
        "the organization first spent a credit."
    ),
)
async def list_entries(
    caller: CanManage,
    session: Session,
    limit: Annotated[int, Query(ge=1, le=ledger.MOST_ENTRIES)] = 50,
) -> list[CreditEntryOut]:
    found = await ledger.entries(session, caller.organization_id, limit=limit)
    return [
        CreditEntryOut(
            id=entry.id,
            at=entry.at,
            kind=cast(Literal["opening", "spend", "grant"], entry.kind),
            delta=entry.delta,
            invoice_id=entry.invoice_id,
        )
        for entry in found
    ]
