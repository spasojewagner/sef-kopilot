"""The tools of the MCP server (ADR-0042). Each does what a route of the API does, through the
same services, with the same checks and the same limits, and answers what the route would: an
HTTP error of the route is the tool's error, in the same words."""

from __future__ import annotations

from typing import Annotated, cast

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.requests import Request

from einvoice_core.pipeline import ValidationReport
from sef_api.auth.dependencies import Principal
from sef_api.auth.permissions import Permission
from sef_api.invoices.routes import count_validation, judged, refuse_when_busy
from sef_api.invoices.validation import ProfileName, Validation
from sef_api.mcp.access import admitted, as_tool_errors
from sef_api.settings import Settings

__all__ = ["register", "validate_invoice"]

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


async def validate_invoice(
    xml: Document, context: Context, profile: Profile = "srb"
) -> ValidationReport:
    """What ``POST /invoices/validate`` does: count a validation, then validate the document in
    memory only."""
    request, caller = admitted(context, Permission.INVOICES_VALIDATE)
    with as_tool_errors():
        validation = await _validated(request, caller, xml, profile)
    return validation.report


async def _validated(
    request: Request, caller: Principal, xml: str, profile: ProfileName
) -> Validation:
    """The validator's report on the document, counted as the routes count an upload's."""
    count_validation(request, caller)
    refuse_when_busy(request)
    settings = cast(Settings, request.app.state.settings)
    content = xml.encode()
    if len(content) > settings.max_invoice_bytes:
        raise ToolError(f"the invoice is larger than {settings.max_invoice_bytes} bytes")
    with judged(request) as validator:
        return await validator.validate(content, profile)
