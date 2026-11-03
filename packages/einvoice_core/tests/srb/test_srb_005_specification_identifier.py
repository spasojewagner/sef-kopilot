"""SRB-005: the specification identifier is the SRB-CIUS identifier."""

from __future__ import annotations

from einvoice_core.srb.codes import SPECIFICATION_IDENTIFIER_EXTENDED
from einvoice_core.srb.rules.srb_005_specification_identifier import RULE

from .conftest import Case


def test_satisfied_by_the_srb_cius_identifier(case: Case) -> None:
    assert case.violations(RULE) == []


def test_satisfied_by_the_extension_identifier(case: Case) -> None:
    case.set_text("cbc:CustomizationID", SPECIFICATION_IDENTIFIER_EXTENDED)

    assert case.violations(RULE) == []


def test_broken_by_the_peppol_identifier(case: Case) -> None:
    peppol = "urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0"

    (violation,) = case.set_text("cbc:CustomizationID", peppol).violations(RULE)

    assert violation.xpath == "/ubl:Invoice/cbc:CustomizationID"
    assert violation.message.endswith(f"found '{peppol}'.")
