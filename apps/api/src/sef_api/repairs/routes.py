"""``/invoices/{invoice_id}/repairs``: patches proposed for a stored invoice, kept with what they
did to a copy of it until a person decides (ADR-0024)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from einvoice_core.patches import MAX_PATCHES, Outcome, Patch
from einvoice_core.pipeline import ValidationReport
from sef_api.auth.dependencies import Principal, check_again, require
from sef_api.auth.permissions import Permission
from sef_api.auth.routes import Problem
from sef_api.db import get_session
from sef_api.invoices import store as invoice_store
from sef_api.invoices.routes import count_validation, judged, refuse_when_busy, scope_of
from sef_api.invoices.validation import ProfileName
from sef_api.models import Repair, RepairStatus
from sef_api.repairs import store

router = APIRouter(prefix="/invoices", tags=["repairs"])

Session = Annotated[AsyncSession, Depends(get_session)]
CanSubmit = Annotated[Principal, Depends(require(Permission.INVOICES_SUBMIT))]


class RepairRequest(BaseModel):
    """Patches to apply to a stored invoice, in order."""

    model_config = ConfigDict(extra="forbid")

    patches: list[Patch] = Field(
        min_length=1,
        max_length=MAX_PATCHES,
        description="Each `{xpath, op, value, reason}`: the canonical path of a place, as a "
        "violation reports it, `replace`, `add` or `remove`, the new text, and why.",
    )


class RepairListed(BaseModel):
    """A repair of an invoice, without the report and the difference."""

    id: uuid.UUID
    invoice_id: uuid.UUID
    status: RepairStatus
    proposed_by: uuid.UUID | None = Field(
        description="The member who proposed it, while their account exists."
    )
    proposed_with_key: bool = Field(description="Whether it came from an API key.")
    proposed_at: datetime
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    changed: bool = Field(description="Whether its patches change the invoice at all.")
    valid: bool = Field(description="Whether the validator finds the patched invoice valid.")
    applied: int = Field(description="Patches that applied.")
    needs_decision: int = Field(
        description="Patches that touch what a person decides: an amount, VAT, a tax or "
        "company identifier, a date or the document's number."
    )
    failed: int = Field(description="Patches that could not apply, each with the reason.")


class RepairOut(RepairListed):
    """A repair of an invoice: what became of each patch, the difference they make, and the
    validator's report on the patched invoice."""

    outcomes: list[Outcome]
    diff: str = Field(description="A unified diff of the invoice before and after, indented alike.")
    report: ValidationReport


def _counted(outcomes: list[Outcome]) -> dict[str, int]:
    return {
        "applied": sum(outcome.status == "applied" for outcome in outcomes),
        "needs_decision": sum(outcome.status == "needs-decision" for outcome in outcomes),
        "failed": sum(outcome.status == "failed" for outcome in outcomes),
    }


def _fields(repair: Repair, outcomes: list[Outcome]) -> dict[str, Any]:
    return {
        "id": repair.id,
        "invoice_id": repair.invoice_id,
        "status": RepairStatus(repair.status),
        "proposed_by": repair.proposed_by,
        "proposed_with_key": repair.key_id is not None,
        "proposed_at": repair.created_at,
        "decided_by": repair.decided_by,
        "decided_at": repair.decided_at,
        "changed": repair.changed,
        "valid": repair.valid,
        **_counted(outcomes),
    }


def _outcomes(repair: Repair) -> list[Outcome]:
    return [Outcome.model_validate(outcome) for outcome in repair.outcomes]


def listed(repair: Repair) -> RepairListed:
    return RepairListed(**_fields(repair, _outcomes(repair)))


def repair_out(repair: Repair) -> RepairOut:
    outcomes = _outcomes(repair)
    return RepairOut(
        **_fields(repair, outcomes),
        outcomes=outcomes,
        diff=repair.diff,
        report=ValidationReport.model_validate(repair.report, strict=False),
    )


def _not_found(what: str = "invoice in this organization") -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"no such {what}")


def _too_many_waiting() -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT,
        f"{store.MAX_WAITING} repairs of this invoice wait for a decision: decide on them first",
    )


_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {
        "model": Problem,
        "description": "No such invoice among those the caller may see, or no such repair of it.",
    }
}
_PROPOSAL: dict[int | str, dict[str, Any]] = _NOT_FOUND | {
    status.HTTP_409_CONFLICT: {
        "model": Problem,
        "description": "As many repairs of the invoice as allowed wait for a decision, or the "
        "invoice changed while the patches were applied to it.",
    },
    status.HTTP_413_CONTENT_TOO_LARGE: {
        "model": Problem,
        "description": "The request body, or the invoice's elements, beyond the server's limit.",
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "model": Problem,
        "description": "The patches are malformed; or the invoice is not well-formed XML, or "
        "could not be validated within the time limit.",
    },
    status.HTTP_429_TOO_MANY_REQUESTS: {
        "model": Problem,
        "description": "Too many validations by the caller, or in their organization; try "
        "again after `Retry-After` seconds.",
    },
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "model": Problem,
        "description": "The validator is busy (retry after `Retry-After` seconds) or not "
        "available on this server.",
    },
}


@router.post(
    "/{invoice_id}/repairs",
    status_code=status.HTTP_201_CREATED,
    summary="Propose a repair of a stored invoice",
    description=(
        "Applies the patches to a copy of the stored invoice, in order, as `einvoice patch` "
        "does, validates what they leave under the invoice's profile, and keeps the repair: "
        "what became of each patch, the difference and the report. The invoice itself does not "
        "change until a person approves the repair. A patch that touches an amount, VAT, a tax "
        "or company identifier, a date or the document's number is not applied: it needs a "
        "person's decision. Counted as a validation. `Location` names the repair."
    ),
    responses=_PROPOSAL,
)
async def propose_repair(
    invoice_id: uuid.UUID,
    proposal: RepairRequest,
    *,
    request: Request,
    response: Response,
    caller: CanSubmit,
    session: Session,
) -> RepairOut:
    count_validation(request, caller)
    scope = scope_of(caller)
    invoice = await invoice_store.find(session, scope, invoice_id)
    content = await invoice_store.content_of(session, scope, invoice_id)
    if invoice is None or content is None:
        raise _not_found()
    if await store.waiting(session, invoice_id) >= store.MAX_WAITING:
        raise _too_many_waiting()
    profile, based_on = cast(ProfileName, invoice.profile), invoice.sha256
    # The checks were this request's database work until the patches are applied: the pooled
    # connection goes back while the validator works.
    await session.commit()
    refuse_when_busy(request)
    with judged(request) as validator:
        patched = await validator.patch(content, profile, proposal.patches)
    # Applying the patches outlasts the transaction in which the permission was checked: a
    # member removed meanwhile, or a key revoked, keeps no repair.
    await check_again(session, caller, Permission.INVOICES_SUBMIT)
    try:
        repair = await store.propose(
            session, caller, invoice_id=invoice_id, based_on=based_on, patched=patched
        )
    except store.TooManyWaitingError:
        raise _too_many_waiting() from None
    except store.InvoiceChangedError:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "the invoice changed while the patches were applied to it: propose them again",
        ) from None
    if repair is None:
        raise _not_found()
    response.headers["Location"] = f"/invoices/{invoice_id}/repairs/{repair.id}"
    return repair_out(repair)


@router.get(
    "/{invoice_id}/repairs",
    summary="List the repairs of a stored invoice",
    description=f"The latest first, at most {store.MAX_LISTED}.",
    responses=_NOT_FOUND,
)
async def list_repairs(
    invoice_id: uuid.UUID, caller: CanSubmit, session: Session
) -> list[RepairListed]:
    if await invoice_store.find(session, scope_of(caller), invoice_id) is None:
        raise _not_found()
    return [listed(repair) for repair in await store.repairs_of(session, invoice_id)]


@router.get(
    "/{invoice_id}/repairs/{repair_id}",
    summary="Read a repair of a stored invoice",
    responses=_NOT_FOUND,
)
async def get_repair(
    invoice_id: uuid.UUID, repair_id: uuid.UUID, caller: CanSubmit, session: Session
) -> RepairOut:
    if await invoice_store.find(session, scope_of(caller), invoice_id) is None:
        raise _not_found()
    repair = await store.find(session, invoice_id, repair_id)
    if repair is None:
        raise _not_found("repair of this invoice")
    return repair_out(repair)
