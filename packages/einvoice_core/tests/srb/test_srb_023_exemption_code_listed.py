"""SRB-023: a VAT exemption reason code is in the Ministry's list."""

from __future__ import annotations

from einvoice_core.srb.rules.srb_023_exemption_code_listed import RULE
from einvoice_core.violations import Severity

from .conftest import Case

CATEGORY = "cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory"


def test_satisfied_by_the_minimal_invoice(case: Case) -> None:
    assert case.violations(RULE) == []


def test_satisfied_by_a_listed_code(credit_note: Case) -> None:
    reason = f"{CATEGORY}[cbc:ID = 'E']/cbc:TaxExemptionReasonCode"

    assert credit_note.set_text(reason, "PDV-RS-24-1-2").violations(RULE) == []


def test_broken_by_an_unlisted_code_as_a_warning(credit_note: Case) -> None:
    """The synthetic credit note carries an EN 16931 VATEX code, not a Serbian one."""
    (violation,) = credit_note.violations(RULE)

    assert violation.severity is Severity.WARNING
    assert violation.xpath == (
        "/cn:CreditNote/cac:TaxTotal[1]/cac:TaxSubtotal[2]/cac:TaxCategory"
        "/cbc:TaxExemptionReasonCode"
    )
    assert "'VATEX-EU-G' (BT-121) is not in the Ministry's list" in violation.message
