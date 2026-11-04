"""One validation, as the validator's process runs it: the work and its outcome as data.

:func:`outcome` is what a validator runs for each document, in its child process or in a
thread (:mod:`sef_api.invoices.validator`). It never raises: what is wrong with the document
is the report, and what goes wrong with the validation is a kind of outcome that carries no
document content, so that it can cross a process boundary and be logged.

Before the validation proper, the elements of the document are counted, without building it,
by a parser as hardened as the validator's own. The cost of validating grows with elements,
not bytes (an embedded PDF is one text node), so a budget of elements bounds the memory and
the time one document can take.

With the report comes a :class:`InvoiceSummary` of what the validator read, for listing a
stored invoice: its number, date, parties and amount due, when it could be read as one.
"""

from __future__ import annotations

import io
from datetime import date
from decimal import Decimal
from typing import Final, Literal

from lxml import etree
from pydantic import BaseModel, ConfigDict, Field

from einvoice_core import schematron, xsd
from einvoice_core.model import DocumentType
from einvoice_core.pipeline import PROFILES, ValidationReport, validate
from einvoice_core.rulesets import RulesetNotFoundError, ruleset_path
from einvoice_core.schematron import SchematronError
from einvoice_core.ubl import build_invoice
from einvoice_core.xml import ParseError, load_document

__all__ = [
    "SUMMARY_TEXT_LIMIT",
    "InvoiceSummary",
    "Kind",
    "Outcome",
    "ProfileName",
    "Validation",
    "count_elements",
    "outcome",
    "rule_sets_missing",
    "summarize",
    "warm_up",
]

#: The profiles a document can be validated against (``einvoice_core.pipeline.PROFILES``).
ProfileName = Literal["srb", "en16931", "peppol"]

#: ``report``: the validator's report and the summary, a :class:`Validation` as JSON.
#: ``too-many-elements``: the document has more elements than the budget allows.
#: ``unavailable``: the rule sets are missing or broken. ``refused``: the rule sets could not
#: be applied to this document. ``failed``: anything else, by the type of the exception only.
Kind = Literal["report", "too-many-elements", "unavailable", "refused", "failed"]
Outcome = tuple[Kind, str]

#: The characters a summary keeps of each text: a list of invoices stays small whatever a
#: document holds.
SUMMARY_TEXT_LIMIT: Final = 200

_EVENTS: Final = ("end",)


class InvoiceSummary(BaseModel):
    """What an invoice says about itself, as the validator read it: enough to list it by."""

    model_config = ConfigDict(frozen=True)

    document_type: DocumentType
    number: str = Field(description="BT-1 invoice number.")
    issue_date: date = Field(description="BT-2 issue date.")
    currency: str | None = Field(description="BT-5 invoice currency code.")
    seller: str | None = Field(description="BT-27 seller name, or BT-28 trading name.")
    buyer: str | None = Field(description="BT-44 buyer name, or BT-45 trading name.")
    payable_amount: Decimal = Field(description="BT-115 amount due, in the invoice currency.")


class Validation(BaseModel):
    """The validator's report on a document, and what it read from it if it could."""

    model_config = ConfigDict(frozen=True)

    report: ValidationReport
    summary: InvoiceSummary | None = Field(
        description="None when the document is not a schema-valid invoice the model can read."
    )


def _packages() -> list[str]:
    """Every fetched package the profiles need: the UBL schemas, the Schematron rule sets and
    the compiler for the rule sets published only as Schematron sources."""
    rule_sets = {name for profile in PROFILES.values() for name in profile.rule_sets}
    packages = {schematron.RULE_SETS[name].package for name in rule_sets}
    return [xsd.UBL_RULESET, *sorted(packages), schematron.COMPILER_PACKAGE]


def rule_sets_missing() -> str | None:
    """Why this server cannot validate, a rule set that has not been fetched, or None."""
    try:
        for package in _packages():
            ruleset_path(package)
    except RulesetNotFoundError as missing:
        return str(missing)
    return None


def warm_up() -> str | None:
    """Compile the UBL schemas and every profile's rule sets now rather than on first use.

    Returns why the validator cannot run, or None. Only the type of an unexpected error is
    kept: its message is not needed to see that the rule sets are broken.
    """
    missing = rule_sets_missing()
    if missing is not None:
        return missing
    try:
        xsd.default_validator()
        for name in sorted({name for profile in PROFILES.values() for name in profile.rule_sets}):
            schematron.default_validator(name)
    except Exception as error:
        return f"the validator's rule sets cannot be loaded ({type(error).__name__})"
    return None


def count_elements(content: bytes, *, limit: int) -> int:
    """The elements of ``content``, counted while it is read and never built, up to ``limit``
    plus one. Malformed XML counts what was read before it: the validator reports it."""
    parser = etree.iterparse(
        io.BytesIO(content),
        events=_EVENTS,
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        huge_tree=False,
    )
    counted = 0
    try:
        for _event, element in parser:
            counted += 1
            if counted > limit:
                break
            element.clear(keep_tail=True)  # what has been counted is not kept
            while (previous := element.getprevious()) is not None:
                parent = element.getparent()
                if parent is None:
                    break
                parent.remove(previous)
    except etree.XMLSyntaxError:
        pass
    return counted


def _short(text: str | None) -> str | None:
    return None if text is None else text[:SUMMARY_TEXT_LIMIT]


def summarize(tree: etree._ElementTree) -> InvoiceSummary | None:
    """What the validator reads from a schema-valid document; None if it is no invoice the
    model can read (say, an amount too long to check)."""
    try:
        invoice = build_invoice(tree.getroot())
    except ParseError:
        return None
    return InvoiceSummary(
        document_type=invoice.document_type,
        number=invoice.id[:SUMMARY_TEXT_LIMIT],
        issue_date=invoice.issue_date,
        currency=_short(invoice.currency),
        seller=_short(invoice.seller.name or invoice.seller.trading_name),
        buyer=_short(invoice.buyer.name or invoice.buyer.trading_name),
        payable_amount=invoice.totals.payable_amount,
    )


def _schema_valid(report: ValidationReport) -> bool:
    return any(
        layer.layer == "xsd" and layer.ran and not layer.violations for layer in report.layers
    )


def outcome(content: bytes, profile: ProfileName, *, max_elements: int) -> Outcome:
    """Validate ``content`` under ``profile``, if it has at most ``max_elements`` elements."""
    if count_elements(content, limit=max_elements) > max_elements:
        return "too-many-elements", f"the invoice has more than {max_elements} elements"
    try:
        try:
            tree = load_document(content)
        except ParseError:  # the validator reports why
            report, summary = validate(content, profile), None
        else:
            report = validate(tree, profile)
            summary = summarize(tree) if _schema_valid(report) else None
    except RulesetNotFoundError:
        return "unavailable", "the validator's rule sets are not installed"
    except SchematronError:
        return "refused", "the rule sets could not be applied to this invoice"
    except Exception as error:
        return "failed", type(error).__name__
    return "report", Validation(report=report, summary=summary).model_dump_json()
