"""SRB-022: a VAT exemption reason code is one of its own category's codes."""

from __future__ import annotations

import pytest

from einvoice_core.srb.rules.srb_022_exemption_code_category import RULE

from .conftest import Case

CATEGORY = "cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory"
REASON = f"{CATEGORY}/cbc:TaxExemptionReasonCode"


def exempt(case: Case, category: str, code: str, percent: str = "0") -> Case:
    case.set_text(f"{CATEGORY}/cbc:ID", category).set_text(f"{CATEGORY}/cbc:Percent", percent)
    fragment = f"<cbc:TaxExemptionReasonCode>{code}</cbc:TaxExemptionReasonCode>"
    return case.insert(CATEGORY, fragment, after="cbc:Percent")


def test_satisfied_without_an_exemption_code(case: Case) -> None:
    assert case.violations(RULE) == []


@pytest.mark.parametrize(
    ("category", "code", "percent"),
    [
        ("E", "PDV-RS-25-1-1", "0"),
        ("O", "PDV-RS-11-1-1", "0"),
        ("N", "PDV-RS-6-1-1 (BN)", "0"),
        ("AE", "PDV-RS-36b-6", "20"),
        ("S", "PDV-RS-OBJ", "10"),
    ],
)
def test_satisfied_by_a_code_of_the_category(
    case: Case, category: str, code: str, percent: str
) -> None:
    assert exempt(case, category, code, percent).violations(RULE) == []


def test_satisfied_by_an_unlisted_code(case: Case) -> None:
    """That is SRB-023's business."""
    assert exempt(case, "E", "VATEX-EU-G").violations(RULE) == []


def test_broken_by_a_code_of_another_category(case: Case) -> None:
    (violation,) = exempt(case, "Z", "PDV-RS-11-1-1").violations(RULE)

    assert violation.xpath == f"/ubl:Invoice/{REASON}"
    assert violation.message == (
        "[SRB-022]-The VAT exemption reason code 'PDV-RS-11-1-1' (BT-121) belongs to category "
        "O in the Ministry's list, not to Z."
    )


def test_broken_by_a_code_of_the_category_at_another_rate(case: Case) -> None:
    (violation,) = exempt(case, "AE", "PDV-RS-36b-6", "10").violations(RULE)

    assert violation.message.endswith(
        "belongs to category AE20 in the Ministry's list, not to AE10."
    )


def test_broken_by_a_code_that_several_categories_share(case: Case) -> None:
    (violation,) = exempt(case, "E", "PDV-RS-10-2-1").violations(RULE)

    assert "belongs to category AE20 or AE10" in violation.message
