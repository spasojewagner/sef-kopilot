"""``/invoices``: the validator's report on an invoice."""

from __future__ import annotations

import logging
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from einvoice_core.pipeline import ValidationReport
from sef_api.auth.dependencies import require
from sef_api.auth.permissions import Permission
from sef_api.auth.routes import Problem
from sef_api.db import get_session
from sef_api.invoices.upload import XML_MEDIA_TYPES, read_invoice
from sef_api.invoices.validation import ProfileName
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
    responses={
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
    },
)
async def validate(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    profile: Annotated[
        ProfileName,
        Query(description="`srb` (SEF), `en16931` or `peppol` (Peppol BIS Billing 3.0)."),
    ] = "srb",
) -> ValidationReport:
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
            report = await validator.validate(content, profile)
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
    response.headers["Cache-Control"] = "no-store"
    return report
