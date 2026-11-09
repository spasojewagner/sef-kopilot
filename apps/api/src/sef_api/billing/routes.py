"""``/billing``: the credits of the caller's organization, where billing is on (ADR-0059), and
buying them, where the server sells them through Stripe's sandbox (ADR-0060).

Whoever may store invoices, and so spend credits, a person or an API key, sees how many are
left and the packs on sale; the owner sees the ledger, every change of them, and opens a
checkout to buy a pack. Stripe tells the API that a checkout was paid by an event it signs,
which is the only request here that no one signs in for: the signature is checked before
anything is read, and a payment is counted once, however often the event comes.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.auth.dependencies import Principal, check_again, require
from sef_api.auth.permissions import Permission
from sef_api.auth.routes import Problem
from sef_api.billing import ledger
from sef_api.billing.payments import Pack, PaymentError, PaymentProvider, UnverifiedReportError
from sef_api.db import get_session
from sef_api.logs import security_event
from sef_api.models import Organization
from sef_api.settings import Settings

router = APIRouter(prefix="/billing", tags=["billing"])

Session = Annotated[AsyncSession, Depends(get_session)]
CanSubmit = Annotated[Principal, Depends(require(Permission.INVOICES_SUBMIT))]
CanManage = Annotated[Principal, Depends(require(Permission.ORGANIZATION_MANAGE))]


class PackOut(BaseModel):
    credits: int
    price: int = Field(description="In the currency's smallest unit (cents).")
    currency: str = Field(description="ISO 4217, in lower case.")


class Billing(BaseModel):
    enabled: bool = Field(
        description="Whether storing an invoice costs a credit on this server; when not, every "
        "other field is null and nothing is sold."
    )
    balance: int | None = Field(description="The credits the organization holds.")
    starting: int | None = Field(description="The credits an organization starts with.")
    per_invoice: int | None = Field(description="The credits one stored invoice costs.")
    packs: list[PackOut] = Field(
        description="The packs an owner may buy (`POST /billing/checkout`); none where the "
        "server sells no credits, and its operator grants them."
    )


class CheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credits: int = Field(description="The pack to buy, by the credits it gives.")


class CheckoutOut(BaseModel):
    url: str = Field(description="Stripe's page where the owner pays, in its sandbox.")


class CreditEntryOut(BaseModel):
    id: uuid.UUID
    at: datetime
    kind: Literal["opening", "spend", "grant", "purchase"] = Field(
        description="`opening`, the starting credits; `spend`, a stored invoice; `grant`, "
        "credits the operator gave; `purchase`, credits the organization bought."
    )
    delta: int = Field(description="The change of the balance: negative for a spend.")
    invoice_id: uuid.UUID | None = Field(
        description="The stored invoice a spend paid for, which may since have been deleted."
    )


def _terms(request: Request) -> ledger.CreditTerms | None:
    return cast(ledger.CreditTerms | None, request.app.state.credit_terms)


def _payments(request: Request) -> PaymentProvider | None:
    return cast(PaymentProvider | None, request.app.state.payments)


def _packs(request: Request) -> list[Pack]:
    if _payments(request) is None:
        return []
    settings = cast(Settings, request.app.state.settings)
    return [Pack(credits=count, price=price) for count, price in settings.credit_packs]


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
        return Billing(enabled=False, balance=None, starting=None, per_invoice=None, packs=[])
    held = await ledger.balance(session, caller.organization_id, terms)
    settings = cast(Settings, request.app.state.settings)
    packs = [
        PackOut(credits=pack.credits, price=pack.price, currency=settings.credit_currency)
        for pack in _packs(request)
    ]
    return Billing(enabled=True, balance=held, starting=terms.starting, per_invoice=1, packs=packs)


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
            kind=cast(Literal["opening", "spend", "grant", "purchase"], entry.kind),
            delta=entry.delta,
            invoice_id=entry.invoice_id,
        )
        for entry in found
    ]


@router.post(
    "/checkout",
    status_code=status.HTTP_201_CREATED,
    summary="Open a checkout to buy credits",
    description=(
        "Opens a Stripe Checkout, in Stripe's sandbox, for one of the packs `GET /billing` "
        "names; the answer is the page where the owner pays, with a test card only. When "
        "Stripe reports the payment, the pack's credits are added to the organization's. The "
        "owner opens it, signed in."
    ),
    responses={
        status.HTTP_502_BAD_GATEWAY: {"model": Problem, "description": "Stripe did not open it."},
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": Problem,
            "description": "This server sells no credits (`STRIPE_SECRET_KEY`, `SEF_WEB_URL`).",
        },
    },
)
async def open_checkout(
    request: Request, body: CheckoutRequest, caller: CanManage, session: Session
) -> CheckoutOut:
    payments = _payments(request)
    settings = cast(Settings, request.app.state.settings)
    if payments is None or settings.web_url is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "this server sells no credits")
    pack = next((p for p in _packs(request) if p.credits == body.credits), None)
    if pack is None:
        on_sale = ", ".join(str(p.credits) for p in _packs(request))
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"no pack gives {body.credits} credits: {on_sale}",
        )
    await check_again(session, caller, Permission.ORGANIZATION_MANAGE)
    page = f"{settings.web_url}/organization"
    try:
        opened = await payments.checkout(
            caller.organization_id,
            pack,
            success_url=f"{page}?checkout=paid",
            cancel_url=f"{page}?checkout=cancelled",
        )
    except PaymentError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from None
    security_event(
        "credits.checkout-opened",
        organization=str(caller.organization_id),
        user=str(caller.user_id),
        credits=pack.credits,
        reference=opened.reference,
    )
    return CheckoutOut(url=opened.url)


@router.post(
    "/stripe-events",
    summary="Receive Stripe's events",
    description=(
        "Where Stripe sends its events, each signed with the endpoint's secret "
        "(`Stripe-Signature`): a checkout paid adds its pack's credits to the organization's, "
        "once, however often the event comes; any other event is acknowledged and ignored. An "
        "event whose signature is not Stripe's, or older than five minutes, answers 400 and "
        "changes nothing."
    ),
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": Problem, "description": "Not Stripe's event."},
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": Problem,
            "description": "This server sells no credits.",
        },
    },
)
async def receive_stripe_event(
    request: Request,
    session: Session,
    stripe_signature: Annotated[str | None, Header()] = None,
) -> dict[str, bool]:
    payments = _payments(request)
    terms = _terms(request)
    if payments is None or terms is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "this server sells no credits")
    payload = await request.body()
    try:
        paid = payments.paid(payload, stripe_signature)
    except UnverifiedReportError as error:
        security_event("credits.event-refused", why=str(error))
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from None
    if paid is None:
        return {"counted": False}
    if await session.get(Organization, paid.organization_id) is None:
        security_event("credits.purchase-unclaimed", reference=paid.reference)
        return {"counted": False}
    counted = await ledger.purchase(
        session, paid.organization_id, terms, count=paid.credits, reference=paid.reference
    )
    await session.commit()
    if counted:
        security_event(
            "credits.purchased",
            organization=str(paid.organization_id),
            credits=paid.credits,
            reference=paid.reference,
        )
    return {"counted": counted}
