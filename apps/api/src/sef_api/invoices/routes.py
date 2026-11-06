"""``/invoices``: the validator's report on an invoice and the explanations of its rules, and the
invoices an organization keeps."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, date, datetime
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
    UnreadableInvoiceError,
    ValidationRefusedError,
    ValidationTimeoutError,
    Validator,
    ValidatorBusyError,
    ValidatorFailedError,
    ValidatorUnavailableError,
)
from sef_api.jobs import store as job_store
from sef_api.jobs.routes import JobOut, job_out
from sef_api.jobs.runners import JobRunner
from sef_api.llm import Language
from sef_api.models import JobKind, StoredInvoice
from sef_api.rag.embeddings import Embedder
from sef_api.rag.explainer import Explainer, Explanation, explain_report
from sef_api.rate_limits import Counted, Limit, RateLimiter, Rule, too_many
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
Explaining = Annotated[
    Language,
    Query(description="The language of the explanations: `sr` (Serbian, Latin script) or `en`."),
]
CanValidate = Annotated[Principal, Depends(require(Permission.INVOICES_VALIDATE))]
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


class InvoiceOut(BaseModel):
    """A stored invoice: who submitted it and when, and what the validator read from it."""

    id: uuid.UUID
    submitted_by: uuid.UUID | None = Field(
        description="The member who submitted it, while their account exists."
    )
    submitted_at: datetime
    validated_at: datetime = Field(
        description="When the validator last judged it: when it was stored, or validated again."
    )
    profile: ProfileName = Field(description="The profile it was validated under.")
    valid: bool = Field(description="Whether the validator found no fatal violation.")
    size: int = Field(description="Bytes of the document.")
    sha256: str = Field(description="SHA-256 digest of the document, in hexadecimal.")
    summary: InvoiceSummary | None = Field(
        description="None when the document is not a schema-valid invoice the validator can read."
    )


class StoredInvoiceOut(InvoiceOut):
    """A stored invoice with the validator's latest report on it."""

    report: ValidationReport


class Explained(BaseModel):
    """The validator's report on an invoice, and the explanations of the rules it names."""

    report: ValidationReport
    day: date = Field(
        description="The day whose law the explanations cite: the invoice's issue date (BT-2), "
        "or today when the invoice cannot be read."
    )
    language: Language
    model: str = Field(description="The language model that wrote the explanations.")
    explanations: list[Explanation] = Field(
        description="One for each rule of the report, those with a fatal violation first."
    )
    unexplained: list[str] = Field(
        description="Rules of the report beyond the most one request explains; ask again for "
        "them once the others are fixed."
    )


class InvoicePage(BaseModel):
    """Stored invoices, the newest first."""

    invoices: list[InvoiceOut]
    next: str | None = Field(
        description="Pass as `after` for the next page; null on the last page."
    )


_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {
        "model": Problem,
        "description": "No such invoice among those the caller may see.",
    }
}
_DOWNLOAD: dict[int | str, dict[str, Any]] = {
    status.HTTP_200_OK: {
        "description": "The UBL 2.1 document.",
        "content": {"application/xml": {"schema": {"type": "string", "format": "binary"}}},
    }
}


def scope_of(caller: Principal) -> store.Scope:
    """The invoices ``caller`` may see: every one of the organization's with
    ``invoices:manage``, otherwise the ones they submitted."""
    if caller.may(Permission.INVOICES_MANAGE):
        return store.Scope(caller.organization_id)
    return store.Scope(caller.organization_id, submitted_by=caller.user_id)


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "no such invoice in this organization")


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
        validated_at=invoice.validated_at,
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
    responses=_VALIDATION_RESPONSES,
)
async def validate(
    request: Request,
    response: Response,
    caller: CanValidate,
    session: Session,
    profile: Profile = "srb",
) -> ValidationReport:
    _, validation = await _validated(request, session, caller, profile)
    response.headers["Cache-Control"] = "no-store"
    return validation.report


_EXPLANATION_RESPONSES: dict[int | str, dict[str, Any]] = _VALIDATION_RESPONSES | {
    status.HTTP_429_TOO_MANY_REQUESTS: {
        "model": Problem,
        "description": "Too many validations or requests to the language model by the caller, "
        "or in their organization; try again after `Retry-After` seconds.",
    },
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "model": Problem,
        "description": "No language model is configured on this server, or the validator is "
        "busy (retry after `Retry-After` seconds) or not available.",
    },
}


@router.post(
    "/explain",
    summary="Explain an invoice's violations",
    description=(
        "Validates the invoice in the request body as `POST /invoices/validate` does, then "
        "explains each rule its report names: what the rule requires, why the invoice fails "
        "it and what to change, citing the passages of the official documents that apply on "
        "the invoice's issue date. Every citation is a passage of the corpus this server "
        "holds. Each rule is explained once, those that make the invoice invalid first, as many "
        "as the server allows in one request; a rule without an explanation says why. Nothing "
        "is stored. The language model is sent each rule's first violation, whose message may "
        "quote the invoice, and the passages; nothing else of the invoice."
    ),
    openapi_extra=_DOCUMENT,
    responses=_EXPLANATION_RESPONSES,
)
async def explain(
    request: Request,
    response: Response,
    *,
    caller: CanValidate,
    session: Session,
    profile: Profile = "srb",
    language: Explaining = "sr",
) -> Explained:
    explainer = cast(Explainer | None, request.app.state.explainer)
    if explainer is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "no language model is configured on this server"
        )
    settings = cast(Settings, request.app.state.settings)
    _, validation = await _validated(request, session, caller, profile, asks_model=True)
    summary = validation.summary
    day = summary.issue_date if summary is not None else datetime.now(UTC).date()
    explanations, unexplained = await explain_report(
        session,
        validation.report,
        day=day,
        language=language,
        explainer=explainer,
        embedder=cast(Embedder | None, request.app.state.embedder),
        max_rules=settings.max_explanations,
        seconds=settings.explanation_seconds,
    )
    response.headers["Cache-Control"] = "no-store"
    return Explained(
        report=validation.report,
        day=day,
        language=language,
        model=explainer.model,
        explanations=explanations,
        unexplained=unexplained,
    )


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
    content, validation = await _validated(request, session, caller, profile)
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


@router.post(
    "/revalidations",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Validate stored invoices again",
    description=(
        "Starts a job that validates again, with the rules this server has now, the stored "
        "invoices the caller may see, as `GET /invoices` lists them, and makes each new report "
        "the invoice's latest. `Location` names the job, which `GET /jobs/{job_id}` reads and "
        "`GET /jobs/{job_id}/events` follows. A member has one revalidation under way at a "
        "time. An invoice whose new report would take the organization past its quota keeps "
        "the report it has; the job counts it."
    ),
    responses={
        status.HTTP_409_CONFLICT: {
            "model": Problem,
            "description": "A revalidation the caller started is under way; `Location` names it.",
        }
    },
)
async def revalidate_invoices(
    request: Request, response: Response, caller: CanSubmit, session: Session
) -> JobOut:
    scope = scope_of(caller)
    job = await job_store.start(
        session,
        organization_id=caller.organization_id,
        submitted_by=caller.user_id,
        kind=JobKind.REVALIDATION,
        parameters={} if scope.submitted_by is None else {"submitted_by": str(scope.submitted_by)},
    )
    if job is None:
        running = await job_store.under_way(
            session, caller.organization_id, caller.user_id, JobKind.REVALIDATION
        )
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "a revalidation you started is under way",
            None if running is None else {"Location": f"/jobs/{running.id}"},
        )
    await cast(JobRunner, request.app.state.jobs).enqueue(job.id)
    response.headers["Location"] = f"/jobs/{job.id}"
    response.headers["Cache-Control"] = "no-store"
    return job_out(job)


@router.get(
    "",
    summary="List stored invoices",
    description=(
        "The organization's stored invoices, the newest first, a page at a time: what the "
        "validator read from each and whether it is valid, without the reports. A member "
        "without `invoices:manage` sees the invoices they submitted. `valid=false` lists only "
        "the invoices the validator last found invalid, `valid=true` only the valid ones."
    ),
    responses={
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": Problem,
            "description": "`after` is not a cursor this API gave.",
        }
    },
)
async def list_invoices(
    response: Response,
    *,
    caller: CanSubmit,
    session: Session,
    limit: Annotated[int, Query(ge=1, le=store.MAX_PAGE, description="Invoices per page.")] = 50,
    after: Annotated[
        str | None,
        Query(max_length=200, description="The `next` of the page before, to continue it."),
    ] = None,
    valid: Annotated[
        bool | None,
        Query(description="Only the invoices whose latest report is valid, or invalid."),
    ] = None,
) -> InvoicePage:
    try:
        page = await store.page_of(session, scope_of(caller), limit=limit, after=after, valid=valid)
    except store.InvalidCursorError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "after is not a cursor this API gave"
        ) from None
    response.headers["Cache-Control"] = "no-store"
    return InvoicePage(invoices=[_invoice(invoice) for invoice in page.invoices], next=page.next)


@router.get(
    "/{invoice_id}",
    summary="Read a stored invoice",
    description="What the validator read from the invoice, and its latest report on it.",
    responses=_NOT_FOUND,
)
async def get_invoice(
    invoice_id: uuid.UUID, response: Response, caller: CanSubmit, session: Session
) -> StoredInvoiceOut:
    invoice = await store.find(session, scope_of(caller), invoice_id)
    if invoice is None:
        raise _not_found()
    response.headers["Cache-Control"] = "no-store"
    return _stored(invoice)


@router.get(
    "/{invoice_id}/content",
    summary="Download a stored invoice",
    description=(
        "The document as it was sent, byte for byte, as an attachment: a browser saves it "
        "rather than renders it."
    ),
    response_class=Response,
    responses=_DOWNLOAD | _NOT_FOUND,
)
async def download_invoice(invoice_id: uuid.UUID, caller: CanSubmit, session: Session) -> Response:
    content = await store.content_of(session, scope_of(caller), invoice_id)
    if content is None:
        raise _not_found()
    return Response(
        content,
        media_type="application/xml",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'attachment; filename="invoice-{invoice_id}.xml"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete(
    "/{invoice_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a stored invoice",
    description=(
        "Deletes the invoice, its document and its report; what the organization stores "
        "shrinks by as much."
    ),
    responses=_NOT_FOUND,
)
async def delete_invoice(invoice_id: uuid.UUID, caller: CanSubmit, session: Session) -> None:
    if not await store.forget(session, scope_of(caller), invoice_id):
        raise _not_found()


def count_validation(request: Request, caller: Principal, *, asks_model: bool = False) -> None:
    """Count a validation, and a request to the language model if it asks the model, against
    the caller's limits and their organization's, all at once; 429 beyond any. A caller is a
    member signed in, whatever the device, or one API key."""
    limiter = cast(RateLimiter, request.app.state.limiter)
    limits = cast(Mapping[Counted, Limit], request.app.state.limits)
    who = (
        f"key {caller.key.key_id}"
        if caller.key is not None
        else f"member {caller.organization_id} {caller.user_id}"
    )
    organization = str(caller.organization_id)
    counted = [(Counted.VALIDATION, Counted.ORGANIZATION_VALIDATION)]
    if asks_model:
        counted.append((Counted.MODEL_REQUEST, Counted.ORGANIZATION_MODEL_REQUEST))
    rules = [
        rule
        for each, together in counted
        for rule in (
            Rule(each, who, limits[each]),
            Rule(together, organization, limits[together]),
        )
    ]
    if (wait := limiter.hit(*rules)) > 0:
        holding = max(rules, key=limiter.wait)
        raise too_many(Counted(holding.name), wait)


async def _validated(
    request: Request,
    session: AsyncSession,
    caller: Principal,
    profile: ProfileName,
    *,
    asks_model: bool = False,
) -> tuple[bytes, Validation]:
    """The invoice in the request body and the validator's report on it with what it read, or
    the HTTP error that says why there is none."""
    # Counted before the body is read, so that nothing is read for a client held back.
    count_validation(request, caller, asks_model=asks_model)
    # The permission check was this request's only database work. Ending its transaction gives
    # the pooled connection back before the body is read and validated, so that neither a slow
    # upload nor a validation waiting for its turn keeps it from other requests.
    await session.commit()
    settings = cast(Settings, request.app.state.settings)
    refuse_when_busy(request)  # turned away before the body is read, not after
    content = await read_invoice(
        request, limit=settings.max_invoice_bytes, seconds=settings.upload_seconds
    )
    with judged(request) as validator:
        return content, await validator.validate(content, profile)


def refuse_when_busy(request: Request) -> None:
    """503 with ``Retry-After`` when as many validations as allowed are waiting or running."""
    if cast(Admission, request.app.state.admission).full:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "the validator is busy",
            {"Retry-After": str(RETRY_AFTER_SECONDS)},
        )


@contextmanager
def judged(request: Request) -> Iterator[Validator]:
    """The validator, admitted for one document; what goes wrong with it becomes the HTTP error
    that says why it cannot judge the document."""
    validator = cast(Validator, request.app.state.validator)
    admission = cast(Admission, request.app.state.admission)
    busy = {"Retry-After": str(RETRY_AFTER_SECONDS)}
    try:
        with admission.admit():
            yield validator
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
    except (ValidationTimeoutError, ValidationRefusedError, UnreadableInvoiceError) as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    except Exception as error:
        # A message may quote the document, which must never reach a log: the type only. The
        # validator's own failures carry nothing else.
        what = str(error) if isinstance(error, ValidatorFailedError) else type(error).__name__
        logger.error("validation failed with %s", what)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "the validator failed on this document"
        ) from None
