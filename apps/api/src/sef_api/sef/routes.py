"""``/invoices/{id}/sef``: a stored invoice sent to SEF's demo environment in its organization's
name, and what SEF answered (ADR-0051)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal, cast

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.auth.dependencies import Principal, require
from sef_api.auth.permissions import Permission
from sef_api.auth.routes import Problem
from sef_api.db import get_session
from sef_api.invoices import store
from sef_api.invoices.routes import judged, refuse_when_busy, scope_of
from sef_api.models import SefSubmission
from sef_api.sef import submissions
from sef_api.sef.keys import Keyring
from sef_api.sef.submissions import NotSendableError, Reason, SefUnusableError
from sef_api.settings import Settings

router = APIRouter(prefix="/invoices", tags=["sef"])

Session = Annotated[AsyncSession, Depends(get_session)]
#: Checked again under the invoice's lock by the sending itself.
CanSend = Annotated[Principal, Depends(require(Permission.INVOICES_SEND))]
CanRead = Annotated[Principal, Depends(require(Permission.INVOICES_SUBMIT))]


class Submission(BaseModel):
    """A stored invoice sent to SEF, and what SEF answered."""

    id: uuid.UUID = Field(description="The submission, and the `requestId` SEF was sent.")
    invoice_id: uuid.UUID
    state: Literal["unconfirmed", "imported", "refused"] = Field(
        description="`unconfirmed`: sent, and SEF's answer not yet read; sending the invoice "
        "again asks SEF again, with the same `requestId`. `imported`: SEF imported it, with "
        "the ids below. `refused`: SEF did not import it (`refusal`)."
    )
    sales_invoice_id: int | None = Field(description="SEF's id of the sales invoice.")
    sef_invoice_id: int | None = Field(description="SEF's id of the invoice.")
    sef_status: str | None = Field(
        description="Where the invoice stands in SEF, as SEF last said (`Sent`, `Approved`, "
        "`Rejected`, …); null until SEF is asked."
    )
    refusal: Literal["invoice", "key"] | None = Field(
        description="Why SEF did not import it: it refused the `invoice`, or the "
        "organization's `key`."
    )
    detail: str | None = Field(
        description="SEF's own words: why it refused the invoice, or its buyer's comment."
    )
    attempts: int = Field(description="How many times SEF was asked to import it.")
    sent_at: datetime
    answered_at: datetime | None = Field(description="When SEF imported or refused it.")
    checked_at: datetime | None = Field(description="When SEF was last asked where it stands.")


class SendConflict(BaseModel):
    """Why an invoice was not sent: a reason a client tells apart and acts on, and the detail,
    in English, for a person."""

    detail: str
    reason: Reason = Field(
        description="`invalid`: the validator does not pass the invoice under SRB-CIUS. "
        "`no-key`: the organization has no key to SEF. `sent`: SEF imported the invoice "
        "already. `unconfirmed`: another version of it was sent, and SEF's answer is not yet "
        "read. `changed`: the invoice changed while it was being validated."
    )


async def answer_not_sendable(_request: Request, error: Exception) -> JSONResponse:
    """The answer to a :class:`NotSendableError`: 409, with its reason and its detail."""
    refused = cast(NotSendableError, error)
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content=SendConflict(reason=refused.reason, detail=refused.detail).model_dump(),
    )


def _out(submission: SefSubmission) -> Submission:
    return Submission.model_validate(submission, from_attributes=True)


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "no such invoice in this organization")


@router.post(
    "/{invoice_id}/sef",
    status_code=status.HTTP_201_CREATED,
    summary="Send a stored invoice to SEF",
    description=(
        "The invoice's document is validated again under SRB-CIUS and sent to SEF's demo "
        "environment, byte for byte, only when the validator passes it, with the "
        "organization's key, which an owner set (`PUT /organization/sef-key`). The answer is "
        "the submission as SEF answered it: `imported`, with SEF's ids; `refused`, with SEF's "
        "words; or `unconfirmed`, when SEF gave no answer, and sending the invoice again asks "
        "SEF again with the same `requestId`, so that it imports the invoice once. An invoice "
        "that SEF imported is not sent again. The audit log records each sending."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {"model": Problem, "description": "No such invoice."},
        status.HTTP_409_CONFLICT: {"model": SendConflict, "description": "Not sent, and why."},
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": Problem,
            "description": "The validator is busy or not available, or the organization's key "
            "cannot be used on this server.",
        },
    },
)
async def send_invoice(
    invoice_id: uuid.UUID, request: Request, response: Response, caller: CanSend, session: Session
) -> Submission:
    # What SEF answers may quote the invoice.
    response.headers["Cache-Control"] = "no-store"
    scope = scope_of(caller)
    invoice = await store.find(session, scope, invoice_id)
    document = await store.content_of(session, scope, invoice_id)
    if invoice is None or document is None:
        raise _not_found()
    # Nothing is held while the document is validated.
    await session.commit()
    refuse_when_busy(request)
    with judged(request) as validator:
        validation = await validator.validate(document, submissions.PROFILE)
    sending = submissions.sendable(invoice, document, validation.report)
    settings = cast(Settings, request.app.state.settings)
    try:
        submission = await submissions.send(
            session,
            caller,
            sending,
            keyring=cast(Keyring | None, request.app.state.sef_keys),
            http=cast(httpx.AsyncClient, request.app.state.sef_http),
            base_url=settings.sef_demo_base_url,
        )
    except SefUnusableError as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from None
    return _out(submission)


@router.get(
    "/{invoice_id}/sef",
    summary="See what SEF answered about a stored invoice",
    description=(
        "Each time the invoice was sent to SEF, the newest first, with what SEF answered and "
        "where the invoice stands in SEF, as SEF last said."
    ),
    responses={status.HTTP_404_NOT_FOUND: {"model": Problem, "description": "No such invoice."}},
)
async def list_submissions(
    invoice_id: uuid.UUID, response: Response, caller: CanRead, session: Session
) -> list[Submission]:
    response.headers["Cache-Control"] = "no-store"
    if await store.find(session, scope_of(caller), invoice_id) is None:
        raise _not_found()
    return [
        _out(submission) for submission in await submissions.submissions_of(session, invoice_id)
    ]
