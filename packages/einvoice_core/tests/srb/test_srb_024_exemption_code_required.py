"""SRB-024: exempt and non-taxed VAT breakdowns give an exemption reason code."""

from __future__ import annotations

import pytest

from einvoice_core.srb.rules.srb_024_exemption_code_required import RULE

from .conftest import Case

CATEGORY = "cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory"


def test_satisfied_by_a_standard_rated_breakdown(case: Case) -> None:
    assert case.violations(RULE) == []


def test_satisfied_by_reverse_charge_without_a_code(case: Case) -> None:
    assert case.set_text(f"{CATEGORY}/cbc:ID", "AE").violations(RULE) == []


def test_satisfied_by_an_exempt_breakdown_with_a_code(credit_note: Case) -> None:
    assert credit_note.violations(RULE) == []


@pytest.mark.parametrize("code", ["Z", "E", "R", "O", "OE", "SS", "N"])
def test_broken_by_a_breakdown_without_a_code(case: Case, code: str) -> None:
    case.set_text(f"{CATEGORY}/cbc:ID", code).set_text(f"{CATEGORY}/cbc:Percent", "0")

    (violation,) = case.violations(RULE)

    assert violation.xpath == f"/ubl:Invoice/{CATEGORY}"
    assert violation.message.startswith(f"[SRB-024]-A VAT breakdown in category {code} (")


def test_broken_by_a_reason_text_without_the_code(credit_note: Case) -> None:
    reason = f"{CATEGORY}[cbc:ID = 'E']/cbc:TaxExemptionReasonCode"

    (violation,) = credit_note.remove(reason).violations(RULE)

    assert "category E (exempt without the right to deduct input VAT)" in violation.message
