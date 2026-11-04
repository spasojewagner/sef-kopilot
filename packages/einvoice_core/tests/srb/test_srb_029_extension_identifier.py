"""SRB-029: an invoice that uses the Serbian extension says so in BT-24."""

from __future__ import annotations

from einvoice_core.srb.codes import SPECIFICATION_IDENTIFIER, SPECIFICATION_IDENTIFIER_EXTENDED
from einvoice_core.srb.rules.srb_029_extension_identifier import RULE
from einvoice_core.violations import Severity

from .conftest import Case

EMPTY_EXTENSION = (
    "<ext:UBLExtensions><ext:UBLExtension><ext:ExtensionContent><sbt:SrbDtExt/>"
    "</ext:ExtensionContent></ext:UBLExtension></ext:UBLExtensions>"
)


def test_satisfied_by_a_final_invoice_under_the_extended_identifier(final_invoice: Case) -> None:
    assert final_invoice.violations(RULE) == []


def test_satisfied_by_either_identifier_without_extension_elements(case: Case) -> None:
    assert case.violations(RULE) == []
    case.set_text("cbc:CustomizationID", SPECIFICATION_IDENTIFIER_EXTENDED)
    assert case.violations(RULE) == []
    case.set_text("cbc:CustomizationID", SPECIFICATION_IDENTIFIER).insert(".", EMPTY_EXTENSION)
    assert case.violations(RULE) == []


def test_broken_by_extension_elements_under_the_short_identifier(final_invoice: Case) -> None:
    final_invoice.set_text("cbc:CustomizationID", SPECIFICATION_IDENTIFIER)

    (violation,) = final_invoice.violations(RULE)

    assert violation.severity is Severity.WARNING
    assert violation.xpath == "/ubl:Invoice/cbc:CustomizationID"
    assert SPECIFICATION_IDENTIFIER_EXTENDED in violation.message
