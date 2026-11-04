"""``/invoices``: the validator's report on an invoice, and the invoices an organization keeps."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from einvoice_core.model import DocumentType
from einvoice_core.pipeline import ValidationReport
from sef_api.auth.dependencies import Principal, check_again, require
from sef_api.auth.permissions import Permission
from sef_api.auth.routes import Problem
from sef_api.db import get_session
from sef_api.invoices import store
from sef_api.invoices.upload import XML_MEDIA_TYPES, read_invoice
from sef_api.invoices.validation import InvoiceSummary, ProfileName, Validation
from sef_api.invoices.validator import (
    Admission,
    TooManyElementsError,
    ValidationRefusedError,
    ValidationTimeoutError,
    Validator,
    ValidatorBusyError,
    ValidatorFailedError,
    ValidatorUnavailableError,
)
from sef_api.models import StoredInvoice
from sef_api.settings import Settings

router = APIRouter(prefix="/invoices", tags=["invoices"])
logger = logging.getLogger(__name__)

_DOCUMENT: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "description": "The invoice or credit note, UBL 2.1 XML.",
        "content": {
            media_type: {"schema": {"type": "string", "format": "binary"}}
            for media_type in sorted(XML_MEDIA_TYPES)
        },
    }
}


#: Seconds a client turned away because the validator is busy should wait before trying again.
RETRY_AFTER_SECONDS = 1

Session = Annotated[AsyncSession, Depends(get_session)]
Profile = Annotated[
    ProfileName,
    Query(description="`srb` (SEF), `en16931` or `peppol` (Peppol BIS Billing 3.0)."),
]
CanSubmit = Annotated[Principal, Depends(require(Permission.INVOICES_SUBMIT))]

_VALIDATION_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_408_REQUEST_TIMEOUT: {
        "model": Problem,
        "description": "The invoice was not received in time.",
    },
    status.HTTP_413_CONTENT_TOO_LARGE: {
        "model": Problem,
        "description": "The invoice has more bytes or elements than this server accepts.",
    },
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {"model": Problem, "description": "Not XML."},
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "model": Problem,
        "description": "The invoice could not be validated within the time limit, or the "
        "rule sets could not be applied to it.",
    },
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "model": Problem,
        "description": "The validator is busy (retry after `Retry-After` seconds) or not "
        "available on this server.",
    },
}


class InvoiceOut(BaseModel):
    """A stored invoice: who submitted it and when, and what the validator read from it."""

    id: uuid.UUID
    submitted_by: uuid.UUID | None = Field(
        description="The member who submitted it, while their account exists."
    )
    submitted_at: datetime
    profile: ProfileName = Field(description="The profile it was validated under.")
    valid: bool = Field(description="Whether the validator found no fatal violation.")
    size: int = Field(description="Bytes of the document.")
    sha256: str = Field(description="SHA-256 digest of the document, in hexadecimal.")
    summary: InvoiceSummary | None = Field(
        description="None when the document is not a schema-valid invoice the validator can read."
    )


class StoredInvoiceOut(InvoiceOut):
    """A stored invoice with the validator's report on it when it was stored."""

    report: ValidationReport


def _summary(invoice: StoredInvoice) -> InvoiceSummary | None:
    """What the validator read, from the columns it was stored in (all or none of them)."""
    if (
        invoice.document_type is None
        or invoice.number is None
        or invoice.issue_date is None
        or invoice.payable_amount is None
    ):
        return None
    return InvoiceSummary(
        document_type=cast(DocumentType, invoice.document_type),
        number=invoice.number,
        issue_date=invoice.issue_date,
        currency=invoice.currency,
        seller=invoice.seller,
        buyer=invoice.buyer,
        payable_amount=invoice.payable_amount,
    )


def _invoice(invoice: StoredInvoice) -> InvoiceOut:
    return InvoiceOut(
        id=invoice.id,
        submitted_by=invoice.submitted_by,
        submitted_at=invoice.created_at,
        profile=cast(ProfileName, invoice.profile),
        valid=invoice.valid,
        size=invoice.size,
        sha256=invoice.sha256,
        summary=_summary(invoice),
    )


def _stored(invoice: StoredInvoice) -> StoredInvoiceOut:
    return StoredInvoiceOut(
        **_invoice(invoice).model_dump(),
        # The core's models are strict, and JSON gave the report's tuples back as lists.
        report=ValidationReport.model_validate(invoice.report, strict=False),
    )


@router.post(
    "/validate",
    summary="Validate an invoice",
    description=(
        "Validates the UBL 2.1 invoice or credit note in the request body against a profile "
        "and returns the validator's report. Nothing is stored: the document lives in memory "
        "for the length of the request (no-store mode). A document the validator cannot read "
        "is a violation in the report, not an error."
    ),
    openapi_extra=_DOCUMENT,
    dependencies=[Depends(require(Permission.INVOICES_VALIDATE))],
    responses=_VALIDATION_RESPONSES,
)
async def validate(
    request: Request, response: Response, session: Session, profile: Profile = "srb"
) -> ValidationReport:
    _, validation = await _validated(request, session, profile)
    response.headers["Cache-Control"] = "no-store"
    return validation.report


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Store an invoice",
    description=(
        "Validates the UBL 2.1 invoice or credit note in the request body as "
        "`POST /invoices/validate` does, then keeps it for the caller's organization with the "
        "validator's report, byte for byte. A document the validator cannot read is stored "
        "too, with the report that says why. `Location` names the stored invoice."
    ),
    openapi_extra=_DOCUMENT,
    responses=_VALIDATION_RESPONSES
    | {
        status.HTTP_507_INSUFFICIENT_STORAGE: {
            "model": Problem,
            "description": "The organization stores as much as it may; delete invoices first.",
        }
    },
)
async def store_invoice(
    request: Request,
    response: Response,
    caller: CanSubmit,
    session: Session,
    profile: Profile = "srb",
) -> StoredInvoiceOut:
    content, validation = await _validated(request, session, profile)
    settings = cast(Settings, request.app.state.settings)
    # The upload and the validation outlast the transaction in which the permission was
    # checked: a member removed meanwhile stores nothing.
    await check_again(session, caller, Permission.INVOICES_SUBMIT)
    try:
        invoice = await store.store(
            session,
            organization_id=caller.organization_id,
            submitted_by=caller.user_id,
            profile=profile,
            content=content,
            validation=validation,
            quota=settings.max_stored_bytes,
        )
    except store.StorageFullError:
        raise HTTPException(
            status.HTTP_507_INSUFFICIENT_STORAGE, "the organization stores as much as it may"
        ) from None
    response.headers["Location"] = f"/invoices/{invoice.id}"
    response.headers["Cache-Control"] = "no-store"
    return _stored(invoice)


async def _validated(
    request: Request, session: AsyncSession, profile: ProfileName
) -> tuple[bytes, Validation]:
    """The invoice in the request body and the validator's report on it with what it read, or
    the HTTP error that says why there is none."""
    # The permission check was this request's only database work. Ending its transaction gives
    # the pooled connection back before the body is read and validated, so that neither a slow
    # upload nor a validation waiting for its turn keeps it from other requests.
    await session.commit()
    settings = cast(Settings, request.app.state.settings)
    validator = cast(Validator, request.app.state.validator)
    admission = cast(Admission, request.app.state.admission)
    busy = {"Retry-After": str(RETRY_AFTER_SECONDS)}
    if admission.full:  # turned away before the body is read, not after
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "the validator is busy", busy)
    content = await read_invoice(
        request, limit=settings.max_invoice_bytes, seconds=settings.upload_seconds
    )
    try:
        with admission.admit():
            return content, await validator.validate(content, profile)
    except ValidatorBusyError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "the validator is busy", busy
        ) from None
    except ValidatorUnavailableError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "the validator is not available"
        ) from None
    except TooManyElementsError as error:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, str(error)) from None
    except (ValidationTimeoutError, ValidationRefusedError) as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    except Exception as error:
        # A message may quote the document, which must never reach a log: the type only. The
        # validator's own failures carry nothing else.
        what = str(error) if isinstance(error, ValidatorFailedError) else type(error).__name__
        logger.error("validation failed with %s", what)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "the validator failed on this document"
        ) from None
