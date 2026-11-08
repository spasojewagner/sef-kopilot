"""``/invoices/{invoice_id}/repairs``: patches proposed for a stored invoice, kept with what they
did to a copy of it until a person decides, and the decision (ADR-0024).

Anyone who may submit invoices proposes, in person or with an API key, patches of their own or
the language model's (ADR-0025). Only a person decides: an approval or a rejection made with an
API key is refused, since a key can leak from the machine it serves.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
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
from sef_api.invoices.store import StorageFullError
from sef_api.invoices.validation import Patched, ProfileName
from sef_api.llm import Language
from sef_api.models import Repair, RepairStatus
from sef_api.repairs import store
from sef_api.repairs.repairer import (
    ROUNDS,
    ModelFailedError,
    NoPatchError,
    NothingToRepairError,
    Repairer,
    RepairTimeoutError,
)
from sef_api.settings import Settings

router = APIRouter(prefix="/invoices", tags=["repairs"])

Session = Annotated[AsyncSession, Depends(get_session)]
CanSubmit = Annotated[Principal, Depends(require(Permission.INVOICES_SUBMIT))]


def in_person(caller: CanSubmit) -> Principal:
    """The caller, if they came in person, with an access token: not with an API key, nor
    through an MCP client."""
    if not caller.in_person:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "a person decides on a repair: sign in to decide, an API key or an MCP client cannot",
        )
    return caller


InPerson = Annotated[Principal, Depends(in_person)]

ConflictReason = Literal[
    "nothing-to-repair",
    "too-many-waiting",
    "invoice-changed",
    "decided",
    "changes-nothing",
    "outcome-changed",
]


class RepairConflict(BaseModel):
    """Why a request about repairs was refused with 409: a reason that a client tells apart
    from the others and acts on, and the detail, in English, for a person."""

    detail: str
    reason: ConflictReason = Field(
        description="`nothing-to-repair`: the invoice is valid. `too-many-waiting`: as many "
        "repairs of the invoice as allowed wait for a decision. `invoice-changed`: the invoice "
        "is not the document the repair was proposed for, or changed while the patches were "
        "applied to it. `decided`: the repair waits for no decision. `changes-nothing`: the "
        "repair changes nothing, so there is nothing to approve. `outcome-changed`: the "
        "patches no longer leave the document they left when they were proposed."
    )


class ConflictError(Exception):
    """A request about repairs that the API refuses with 409, and why (:class:`RepairConflict`)."""

    def __init__(self, reason: ConflictReason, detail: str) -> None:
        super().__init__(detail)
        self.reason: ConflictReason = reason
        self.detail = detail


async def answer_conflict(_request: Request, error: Exception) -> JSONResponse:
    """The answer to a :class:`ConflictError`: 409, with its reason and its detail."""
    conflict = cast(ConflictError, error)
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content=RepairConflict(reason=conflict.reason, detail=conflict.detail).model_dump(),
    )


Reasons = Annotated[
    Language,
    Query(
        description="The language of the patches' reasons: `sr` (Serbian, Latin script) or `en`."
    ),
]


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
    model: str | None = Field(
        description="The language model that wrote the patches, when one did: the member who "
        "proposed the repair asked it for them."
    )
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
        "model": repair.model,
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


def _too_many_waiting() -> ConflictError:
    return ConflictError(
        "too-many-waiting",
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
        "model": RepairConflict,
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
        raise ConflictError(
            "invoice-changed",
            "the invoice changed while the patches were applied to it: propose them again",
        ) from None
    if repair is None:
        raise _not_found()
    response.headers["Location"] = f"/invoices/{invoice_id}/repairs/{repair.id}"
    return repair_out(repair)


_SUGGESTION: dict[int | str, dict[str, Any]] = _PROPOSAL | {
    status.HTTP_409_CONFLICT: {
        "model": RepairConflict,
        "description": "The invoice is valid; or as many of its repairs as allowed wait for a "
        "decision; or it changed while the model's patches were applied to it.",
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "model": Problem,
        "description": "The language model proposed no patch that a repair keeps; or the invoice "
        "is not well-formed XML, or could not be validated within the time limit.",
    },
    status.HTTP_429_TOO_MANY_REQUESTS: {
        "model": Problem,
        "description": "Too many validations or requests to the language model by the caller, "
        "or in their organization; try again after `Retry-After` seconds.",
    },
    status.HTTP_502_BAD_GATEWAY: {
        "model": Problem,
        "description": "The language model gave no answer, or none that could be used.",
    },
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "model": Problem,
        "description": "No language model is configured on this server; or the validator is "
        "busy (retry after `Retry-After` seconds) or not available.",
    },
    status.HTTP_504_GATEWAY_TIMEOUT: {
        "model": Problem,
        "description": "The language model proposed no repair within the time allowed.",
    },
}


@router.post(
    "/{invoice_id}/repairs/suggestion",
    status_code=status.HTTP_201_CREATED,
    summary="Have the language model propose a repair of a stored invoice",
    description=(
        "Asks the language model for patches that repair the stored invoice's fatal "
        "violations, and keeps them as a repair the caller proposes: the invoice itself does "
        "not change until a person approves it. The model is sent the violations, whose "
        "messages may quote the invoice, and the invoice's fields around them, by canonical "
        "path; nothing else of it. Every answer is checked before anything is applied: each "
        "patch at a canonical path, writing no value the model was not given. The patches are "
        "applied to a copy and validated, as `POST /invoices/{invoice_id}/repairs` does; while "
        f"fatal violations remain, the model is shown what became of each patch, for {ROUNDS} "
        "rounds within the server's time limit. A patch that failed is not kept; one that "
        "touches an amount, VAT, a tax or company identifier, a date or the document's number "
        "is kept as needing a person's decision. Counted as a validation and as a request to "
        "the language model. `Location` names the repair."
    ),
    responses=_SUGGESTION,
)
async def suggest_repair(
    invoice_id: uuid.UUID,
    *,
    request: Request,
    response: Response,
    caller: CanSubmit,
    session: Session,
    language: Reasons = "sr",
) -> RepairOut:
    repairer = cast(Repairer | None, request.app.state.repairer)
    if repairer is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "no language model is configured on this server"
        )
    count_validation(request, caller, asks_model=True)
    scope = scope_of(caller)
    invoice = await invoice_store.find(session, scope, invoice_id)
    content = await invoice_store.content_of(session, scope, invoice_id)
    if invoice is None or content is None:
        raise _not_found()
    if await store.waiting(session, invoice_id) >= store.MAX_WAITING:
        raise _too_many_waiting()
    profile, based_on = cast(ProfileName, invoice.profile), invoice.sha256
    settings = cast(Settings, request.app.state.settings)
    # No connection is held while the model and the validator work.
    await session.commit()

    async def apply(patches: Sequence[Patch]) -> Patched:
        refuse_when_busy(request)
        with judged(request) as validator:
            return await validator.patch(content, profile, patches, fields=True)

    try:
        suggestion = await repairer.suggest(
            apply, language=language, seconds=settings.repair_seconds
        )
    except NothingToRepairError as error:
        raise ConflictError("nothing-to-repair", str(error)) from None
    except NoPatchError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    except ModelFailedError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from None
    except RepairTimeoutError as error:
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, str(error)) from None
    await check_again(session, caller, Permission.INVOICES_SUBMIT)
    written = store.Written(model=repairer.model, rounds=suggestion.rounds)
    try:
        repair = await store.propose(
            session,
            caller,
            invoice_id=invoice_id,
            based_on=based_on,
            patched=suggestion.patched,
            written=written,
        )
    except store.TooManyWaitingError:
        raise _too_many_waiting() from None
    except store.InvoiceChangedError:
        raise ConflictError(
            "invoice-changed",
            "the invoice changed while the model's patches were applied to it: ask again",
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


def _decided(error: store.DecidedError) -> ConflictError:
    return ConflictError("decided", f"the repair is {error.status}: it waits for no decision")


def _stale() -> ConflictError:
    return ConflictError(
        "invoice-changed", "the invoice changed since the repair was proposed: propose it again"
    )


_DECISION: dict[int | str, dict[str, Any]] = _NOT_FOUND | {
    status.HTTP_403_FORBIDDEN: {
        "model": Problem,
        "description": "The caller came with an API key: only a person decides on a repair.",
    },
    status.HTTP_409_CONFLICT: {
        "model": RepairConflict,
        "description": "The repair waits for no decision, changes nothing, or was proposed for "
        "a document the invoice no longer is.",
    },
}
_APPROVAL: dict[int | str, dict[str, Any]] = (
    _PROPOSAL
    | _DECISION
    | {
        status.HTTP_409_CONFLICT: {
            "model": RepairConflict,
            "description": "The repair waits for no decision or changes nothing; or the "
            "invoice, or what its patches leave, is not what it was when they were proposed.",
        },
        status.HTTP_507_INSUFFICIENT_STORAGE: {
            "model": Problem,
            "description": "The patched invoice would take the organization past its quota.",
        },
    }
)


@router.post(
    "/{invoice_id}/repairs/{repair_id}/approval",
    summary="Approve a repair",
    description=(
        "A person approves the repair, in person: never with an API key. Its patches are "
        "applied again to the invoice, which must still be the document they were proposed "
        "for, and must leave the document they left then. The invoice becomes that document, "
        "with the validator's report on it, within the organization's storage quota; the other "
        "repairs that waited for the invoice are superseded. Counted as a validation."
    ),
    responses=_APPROVAL,
)
async def approve_repair(
    invoice_id: uuid.UUID,
    repair_id: uuid.UUID,
    *,
    request: Request,
    caller: InPerson,
    session: Session,
) -> RepairOut:
    count_validation(request, caller)
    scope = scope_of(caller)
    invoice = await invoice_store.find(session, scope, invoice_id)
    content = await invoice_store.content_of(session, scope, invoice_id)
    if invoice is None or content is None:
        raise _not_found()
    repair = await store.find(session, invoice_id, repair_id)
    if repair is None:
        raise _not_found("repair of this invoice")
    if repair.status != RepairStatus.PROPOSED:
        raise _decided(store.DecidedError(repair.status))
    if not repair.changed:
        raise ConflictError(
            "changes-nothing", "the repair changes nothing: there is nothing to approve"
        )
    if invoice.sha256 != repair.based_on:
        raise _stale()
    profile = cast(ProfileName, invoice.profile)
    patches = [outcome.patch for outcome in _outcomes(repair)]
    settings = cast(Settings, request.app.state.settings)
    await session.commit()  # the connection goes back while the validator works
    refuse_when_busy(request)
    with judged(request) as validator:
        patched = await validator.patch(content, profile, patches)
    await check_again(session, caller, Permission.INVOICES_SUBMIT)
    try:
        approved = await store.approve(
            session,
            caller,
            invoice_id=invoice_id,
            repair_id=repair_id,
            patched=patched,
            quota=settings.max_stored_bytes,
        )
    except store.DecidedError as error:
        raise _decided(error) from None
    except store.InvoiceChangedError:
        raise _stale() from None
    except store.PatchesChangedError:
        raise ConflictError(
            "outcome-changed",
            "the patches no longer leave the document they left when they were proposed: "
            "propose them again",
        ) from None
    except StorageFullError:
        raise HTTPException(
            status.HTTP_507_INSUFFICIENT_STORAGE, "the organization stores as much as it may"
        ) from None
    if approved is None:
        raise _not_found("repair of this invoice")
    return repair_out(approved)


@router.post(
    "/{invoice_id}/repairs/{repair_id}/rejection",
    summary="Reject a repair",
    description="A person rejects the repair, in person: never with an API key. The invoice "
    "stays as it is.",
    responses=_DECISION,
)
async def reject_repair(
    invoice_id: uuid.UUID, repair_id: uuid.UUID, caller: InPerson, session: Session
) -> RepairOut:
    if await invoice_store.find(session, scope_of(caller), invoice_id) is None:
        raise _not_found()
    try:
        rejected = await store.reject(session, caller, invoice_id=invoice_id, repair_id=repair_id)
    except store.DecidedError as error:
        raise _decided(error) from None
    if rejected is None:
        raise _not_found("repair of this invoice")
    return repair_out(rejected)
