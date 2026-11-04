"""SRB-CIUS: the Serbian rules for domestic e-invoices, authored from the specification.

The Ministry of Finance publishes SRB-CIUS, the Serbian core invoice usage specification of
EN 16931 for invoices exchanged through SEF, as a table of usage notes on the EN 16931
business terms, not as Schematron and not with rule identifiers. This package turns those
notes into executable rules: one rule per module in :mod:`einvoice_core.srb.rules`, each with
its own identifier (``SRB-001`` …), the business terms it concerns, the passage of the official
document it comes from, and tests with a document that satisfies it and one that breaks it.

:func:`validate_srb` runs every rule and returns violations in the shared model, with
``layer = "srb-cius"``. Like the EN 16931 Schematron, the rules assume a schema-valid
document, from which the typed model can be built.
"""

from __future__ import annotations

from typing import Final

from lxml import etree

from einvoice_core import model
from einvoice_core.numbers import exact
from einvoice_core.srb.rule import Document, Finding, Reference, Rule
from einvoice_core.srb.rules import load_rules
from einvoice_core.srb.sources import SOURCES, Source
from einvoice_core.ubl import build_invoice
from einvoice_core.violations import Violation
from einvoice_core.xml import canonical_xpath, sibling_index

__all__ = [
    "RULES",
    "SOURCES",
    "Document",
    "Finding",
    "Reference",
    "Rule",
    "Source",
    "validate_srb",
]

#: Every SRB-CIUS rule, in identifier order.
RULES: Final[tuple[Rule, ...]] = load_rules()


def _violation(rule: Rule, finding: Finding) -> Violation:
    element = finding.element
    xpath = None if element is None else canonical_xpath(element)
    if xpath is not None and finding.attribute:
        xpath = f"{xpath}/@{finding.attribute}"
    return Violation(
        rule_id=rule.id,
        severity=rule.severity,
        message=f"[{rule.id}]-{finding.message}",
        xpath=xpath,
        layer="srb-cius",
        line=None if element is None else element.sourceline,
    )


@sibling_index()
def validate_srb(
    tree: etree._ElementTree,
    invoice: model.Invoice | None = None,
    *,
    rules: tuple[Rule, ...] = RULES,
) -> tuple[Violation, ...]:
    """The SRB-CIUS violations of a schema-valid document, rule by rule.

    ``invoice`` is the model of ``tree`` when the caller has already built it; otherwise it is
    built here (which raises :class:`einvoice_core.xml.ParseError` for a document the model
    cannot represent).
    """
    document = Document(tree=tree, invoice=invoice or build_invoice(tree.getroot()))
    with exact():
        return tuple(
            _violation(rule, finding) for rule in rules for finding in rule.check(document)
        )
