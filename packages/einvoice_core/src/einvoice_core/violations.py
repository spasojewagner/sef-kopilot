"""The violation: what every validation layer reports.

XSD validation, the EN 16931 and Peppol Schematron rule sets, the SRB-CIUS rules and the
arithmetic checks all produce the same value, so that the explainer, the repairer, the API
and the evaluation harness can treat them uniformly (ADR-0002). A violation says *which rule*
failed, *how bad* it is, *where* in the original document, and *what* the rule source said.

A violation message may quote values from the invoice (an XSD error repeats the invalid date,
a Schematron message may repeat an amount). Violations are returned to the caller who sent the
document; they are never written to logs or traces.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["Severity", "ValidationLayer", "Violation", "is_valid"]


class Severity(StrEnum):
    """How a violation affects the document.

    The values are the ``flag`` values used by the EN 16931 and Peppol Schematron rule sets.
    """

    FATAL = "fatal"
    """The document must not be sent in this state (SEF or a Peppol access point rejects it)."""

    WARNING = "warning"
    """The document is acceptable, but something is likely wrong or will become an error."""


ValidationLayer = Literal["xml", "xsd", "schematron", "srb-cius", "arithmetic"]
"""The validation layer that produced a violation, in the order the validator runs them.

``xml`` is for a document that cannot be read at all (not well-formed, a DOCTYPE, too large)
or, though schema-valid, cannot be read as an invoice.
"""


class Violation(BaseModel):
    """One failed rule, located in the original document."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    rule_id: str = Field(
        description=(
            "Identifier of the failed rule as published by its source: `XSD` for schema "
            "validity, `BR-CO-15` for EN 16931, `PEPPOL-EN16931-R001` for Peppol, `SRB-…` for "
            "the Serbian rules."
        )
    )
    severity: Severity
    message: str = Field(
        description="What the rule source reports, in English. May quote document values."
    )
    xpath: str | None = Field(
        description=(
            "Canonical XPath of the offending element (see `einvoice_core.xml.canonical_xpath`), "
            "or null when the problem concerns the document as a whole or cannot be located."
        )
    )
    layer: ValidationLayer
    code: str | None = Field(
        default=None,
        description=(
            "Source-specific detail code, e.g. the libxml2 error type of an XSD violation "
            "(`SCHEMAV_ELEMENT_CONTENT`), used to pick an explanation template."
        ),
    )
    line: int | None = Field(
        default=None, description="1-based line in the original document, when known."
    )


def is_valid(violations: tuple[Violation, ...] | list[Violation]) -> bool:
    """A document is valid when no violation is fatal; warnings do not block it."""
    return all(violation.severity is not Severity.FATAL for violation in violations)
