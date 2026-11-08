"""The tools of the MCP server (ADR-0042). Each does what a route of the API does, through the
same services, with the same checks and the same limits, and answers what the route would: an
HTTP error of the route is the tool's error, in the same words."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, cast

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.requests import Request

from einvoice_core.pipeline import ValidationReport
from sef_api.auth.dependencies import Principal, check_again
from sef_api.auth.permissions import Permission
from sef_api.db import Database
from sef_api.invoices import store
from sef_api.invoices.routes import (
    Explained,
    InvoiceOut,
    InvoicePage,
    RevalidationUnderWayError,
    StoredInvoiceOut,
    count_validation,
    explain_stored,
    judged,
    present,
    present_stored,
    refuse_when_busy,
    scope_of,
    start_revalidation,
)
from sef_api.invoices.validation import ProfileName, Validation
from sef_api.jobs import store as job_store
from sef_api.jobs.routes import JobOut, job_out
from sef_api.jobs.routes import scope as jobs_scope
from sef_api.llm import Language
from sef_api.mcp.access import admitted, as_tool_errors
from sef_api.rag.embeddings import Embedder
from sef_api.rag.explainer import Explainer, explain_report
from sef_api.settings import Settings

__all__ = [
    "explain_errors",
    "explain_invoice",
    "get_invoice",
    "get_job",
    "list_invoices",
    "register",
    "revalidate_invoices",
    "store_invoice",
    "validate_invoice",
]

Document = Annotated[
    str, Field(description="The invoice's XML document as text: a UBL 2.1 Invoice or CreditNote.")
]
Profile = Annotated[
    ProfileName,
    Field(
        description="`srb` (SRB-CIUS, the profile of SEF), `en16931` or `peppol` "
        "(Peppol BIS Billing 3.0)."
    ),
]
Explaining = Annotated[
    Language,
    Field(description="The language of the explanations: `sr` (Serbian, Latin script) or `en`."),
]
InvoiceId = Annotated[
    uuid.UUID,
    Field(description="The stored invoice's id, as store_invoice or list_invoices gave it."),
]
JobId = Annotated[
    uuid.UUID,
    Field(description="The job's id, as revalidate_invoices gave it."),
]


def register(server: MCPServer) -> None:
    """Offer every tool on ``server``, with what a client is told about each."""
    server.add_tool(
        validate_invoice,
        name="validate_invoice",
        title="Validate an e-invoice",
        description=(
            "Validate a UBL 2.1 invoice or credit note, given as its XML text, against a "
            "profile: SRB-CIUS (`srb`, the profile of SEF, the Serbian e-invoicing system; the "
            "default), EN 16931 (`en16931`) or Peppol BIS Billing 3.0 (`peppol`). "
            "Deterministic: the rule sets decide, never a language model. The report says "
            "whether the invoice is valid and lists each violation with its rule, severity, "
            "message and the XPath of the element it concerns; a document the validator cannot "
            "read is a violation too. Nothing is stored. Each call counts as a validation "
            "against the caller's limit and their organization's."
        ),
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    server.add_tool(
        explain_errors,
        name="explain_errors",
        title="Explain an e-invoice's errors",
        description=(
            "Validate a UBL 2.1 invoice or credit note as validate_invoice does, then explain "
            "each rule its report names, in Serbian (`sr`, the default) or English (`en`): what "
            "the rule requires, why the invoice fails it and what to change, citing the "
            "passages of the official documents that apply on the invoice's issue date, each "
            "with its source and the dates it is in force. Every citation is a passage this "
            "server holds; quote them rather than adding law of your own. The rules that make "
            "the invoice invalid are explained first, as many as one call allows; the others "
            "are listed as unexplained. A rule without an explanation says why. Nothing is "
            "stored. The language model of this server is sent each rule's first violation, "
            "whose message may quote the invoice, and the passages, nothing else of it. Each "
            "call counts as a validation and as a request to the language model against the "
            "caller's limits and their organization's."
        ),
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        ),
    )

    server.add_tool(
        store_invoice,
        name="store_invoice",
        title="Store an e-invoice",
        description=(
            "Validate a UBL 2.1 invoice or credit note as validate_invoice does, then keep it "
            "for the person's organization with the validator's report, byte for byte, as they "
            "would by uploading it. A document the validator cannot read is stored too, with the "
            "report that says why. The answer is the stored invoice: its id, what the validator "
            "read from it, and the report. Counts as a validation against the caller's limit and "
            "their organization's, and against how much the organization may store."
        ),
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        ),
    )
    server.add_tool(
        list_invoices,
        name="list_invoices",
        title="List stored e-invoices",
        description=(
            "The invoices the person stored, the newest first, each with its number, dates, "
            "parties, totals and whether its latest report is valid; only the valid or the "
            "invalid ones if asked. Pass a page's `next` as `after` for the next page."
        ),
        annotations=ToolAnnotations(
            read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
        ),
    )
    server.add_tool(
        get_invoice,
        name="get_invoice",
        title="Read a stored e-invoice",
        description=(
            "A stored invoice of the person's: what the validator read from it and its latest "
            "report, with every violation."
        ),
        annotations=ToolAnnotations(
            read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
        ),
    )
    server.add_tool(
        explain_invoice,
        name="explain_invoice",
        title="Explain a stored e-invoice's errors",
        description=(
            "Explain each rule a stored invoice's latest report names, as explain_errors does "
            "for a document given as text, in Serbian (`sr`, the default) or English (`en`), "
            "with the passages of the official documents that apply on its issue date. The "
            "invoice is not validated again: the report explained comes with the answer. "
            "Explanations once written in full are kept with the invoice, and read again, "
            "asking the language model nothing and counting nothing, until its report is "
            "another; otherwise the call counts as a request to the language model against "
            "the caller's limit and their organization's."
        ),
        # What it keeps is what it answered, for the same report: nothing of the person's
        # changes, and the next call reads it back.
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        ),
    )
    server.add_tool(
        revalidate_invoices,
        name="revalidate_invoices",
        title="Validate stored e-invoices again",
        description=(
            "Start a job that validates again, with the rules this server has now, the "
            "invoices list_invoices lists, and makes each new report the invoice's latest; "
            "what the invoices hold does not change. The answer is the job, which get_job "
            "reads. One revalidation the person started runs at a time. An invoice whose new "
            "report would take the organization past how much it may store keeps the report it "
            "has; the job counts it."
        ),
        # A report is the validator's, written again from the invoice: none is lost that the
        # rules of today would not write again.
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        ),
    )
    server.add_tool(
        get_job,
        name="get_job",
        title="Read a job",
        description=(
            "Where a job the person started is, how far it has come and, once it has finished, "
            "how it ended: for a revalidation, how many invoices are valid, invalid, kept their "
            "report, failed or were deleted meanwhile."
        ),
        annotations=ToolAnnotations(
            read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
        ),
    )


async def store_invoice(
    xml: Document, context: Context, profile: Profile = "srb"
) -> StoredInvoiceOut:
    """What ``POST /invoices`` does: count a validation, validate the document, then keep it
    with its report for the organization."""
    request, caller = admitted(context, Permission.INVOICES_SUBMIT)
    settings = cast(Settings, request.app.state.settings)
    with as_tool_errors():
        validation = await _validated(request, caller, xml, profile)
    async with cast(Database, request.app.state.database).sessions() as session:
        with as_tool_errors():
            # The validation outlasts the moment the caller was checked: a member removed, or a
            # consent revoked, meanwhile stores nothing.
            await check_again(session, caller, Permission.INVOICES_SUBMIT)
        try:
            invoice = await store.store(
                session,
                organization_id=caller.organization_id,
                submitted_by=caller.user_id,
                profile=profile,
                content=xml.encode(),
                validation=validation,
                quota=settings.max_stored_bytes,
            )
        except store.StorageFullError:
            raise ToolError("the organization stores as much as it may") from None
        return present_stored(invoice)


async def list_invoices(
    context: Context,
    valid: Annotated[
        bool | None,
        Field(description="Only the invoices whose latest report is valid, or invalid."),
    ] = None,
    limit: Annotated[int, Field(ge=1, le=store.MAX_PAGE, description="Invoices per page.")] = 20,
    after: Annotated[
        str | None,
        Field(max_length=200, description="The `next` of the page before, to continue it."),
    ] = None,
) -> InvoicePage:
    """What ``GET /invoices`` does, for the invoices the caller may see."""
    _, caller, database = _reading(context)
    async with database.sessions() as session:
        try:
            page = await store.page_of(
                session, scope_of(caller), limit=limit, after=after, valid=valid
            )
        except store.InvalidCursorError:
            raise ToolError("after is not a cursor this server gave") from None
        invoices: list[InvoiceOut] = [present(invoice) for invoice in page.invoices]
    return InvoicePage(invoices=invoices, next=page.next)


async def get_invoice(invoice_id: InvoiceId, context: Context) -> StoredInvoiceOut:
    """What ``GET /invoices/{invoice_id}`` does."""
    _, caller, database = _reading(context)
    async with database.sessions() as session:
        invoice = await store.find(session, scope_of(caller), invoice_id)
        if invoice is None:
            raise ToolError("no such invoice")
        return present_stored(invoice)


async def explain_invoice(
    invoice_id: InvoiceId, context: Context, language: Explaining = "sr"
) -> Explained:
    """What ``POST /invoices/{invoice_id}/explanations`` does: the kept explanations of the
    invoice's latest report, or the language model's, counted."""
    request, caller, database = _reading(context)
    async with database.sessions() as session:
        invoice = await store.find(session, scope_of(caller), invoice_id)
        if invoice is None:
            raise ToolError("no such invoice")
        with as_tool_errors():
            return await explain_stored(request, caller, session, invoice, language)


async def revalidate_invoices(context: Context) -> JobOut:
    """What ``POST /invoices/revalidations`` does: start the job, and answer it."""
    request, caller, database = _reading(context)
    async with database.sessions() as session:
        try:
            job = await start_revalidation(request, caller, session)
        except RevalidationUnderWayError as under_way:
            named = f": job {under_way.job_id}, as get_job reads" if under_way.job_id else ""
            raise ToolError(f"a revalidation you started is under way{named}") from None
        return job_out(job)


async def get_job(job_id: JobId, context: Context) -> JobOut:
    """What ``GET /jobs/{job_id}`` does."""
    _, caller, database = _reading(context)
    async with database.sessions() as session:
        job = await job_store.find(session, jobs_scope(caller), job_id)
        if job is None:
            raise ToolError("no such job")
        return job_out(job)


def _reading(context: Context) -> tuple[Request, Principal, Database]:
    """The request, the caller who may read stored invoices, and the database."""
    request, caller = admitted(context, Permission.INVOICES_SUBMIT)
    return request, caller, cast(Database, request.app.state.database)


async def validate_invoice(
    xml: Document, context: Context, profile: Profile = "srb"
) -> ValidationReport:
    """What ``POST /invoices/validate`` does: count a validation, then validate the document in
    memory only."""
    request, caller = admitted(context, Permission.INVOICES_VALIDATE)
    with as_tool_errors():
        validation = await _validated(request, caller, xml, profile)
    return validation.report


async def explain_errors(
    xml: Document, context: Context, profile: Profile = "srb", language: Explaining = "sr"
) -> Explained:
    """What ``POST /invoices/explain`` does: count a validation and a request to the model,
    validate the document in memory only, then explain the rules its report names."""
    request, caller = admitted(context, Permission.INVOICES_VALIDATE)
    explainer = cast(Explainer | None, request.app.state.explainer)
    if explainer is None:
        raise ToolError("no language model is configured on this server")
    settings = cast(Settings, request.app.state.settings)
    with as_tool_errors():
        validation = await _validated(request, caller, xml, profile, asks_model=True)
    summary = validation.summary
    day = summary.issue_date if summary is not None else datetime.now(UTC).date()
    async with cast(Database, request.app.state.database).sessions() as session:
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
    return Explained(
        report=validation.report,
        day=day,
        language=language,
        model=explainer.model,
        explanations=explanations,
        unexplained=unexplained,
        written_at=datetime.now(UTC),
    )


async def _validated(
    request: Request, caller: Principal, xml: str, profile: ProfileName, *, asks_model: bool = False
) -> Validation:
    """The validator's report on the document, counted as the routes count an upload's: a
    validation, and a request to the model if one is asked."""
    count_validation(request, caller, asks_model=asks_model)
    refuse_when_busy(request)
    settings = cast(Settings, request.app.state.settings)
    content = xml.encode()
    if len(content) > settings.max_invoice_bytes:
        raise ToolError(f"the invoice is larger than {settings.max_invoice_bytes} bytes")
    with judged(request) as validator:
        return await validator.validate(content, profile)
