"""SRB-021: categories S and AE are charged at 20 or 10 percent."""

from __future__ import annotations

import pytest

from einvoice_core.srb.rules.srb_021_vat_rates import RULE

from .conftest import Case

CATEGORY = "cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory"
LINE = "cac:InvoiceLine/cac:Item/cac:ClassifiedTaxCategory"


@pytest.mark.parametrize("percent", ["20", "10", "20.00", "10.0"])
def test_satisfied_by_the_two_rates(case: Case, percent: str) -> None:
    case.set_text(f"{CATEGORY}/cbc:Percent", percent).set_text(f"{LINE}/cbc:Percent", percent)

    assert case.violations(RULE) == []


def test_satisfied_by_reverse_charge_at_a_serbian_rate(case: Case) -> None:
    case.set_text(f"{CATEGORY}/cbc:ID", "AE").set_text(f"{LINE}/cbc:ID", "AE")

    assert case.violations(RULE) == []


def test_satisfied_by_categories_without_a_rate_of_their_own(case: Case) -> None:
    case.set_text(f"{CATEGORY}/cbc:ID", "E").set_text(f"{CATEGORY}/cbc:Percent", "0")

    assert case.violations(RULE) == []


@pytest.mark.parametrize(("code", "percent"), [("S", "15"), ("S", "0"), ("AE", "0")])
def test_broken_by_another_rate(case: Case, code: str, percent: str) -> None:
    case.set_text(f"{CATEGORY}/cbc:ID", code).set_text(f"{CATEGORY}/cbc:Percent", percent)

    (violation,) = case.violations(RULE)

    assert violation.xpath == f"/ubl:Invoice/{CATEGORY}/cbc:Percent"
    assert violation.message == (
        f"[SRB-021]-The VAT breakdown VAT category {code} is charged at 20 or 10 percent, "
        f"stated in the rate (BT-119); found {percent}."
    )


def test_broken_by_a_missing_rate(case: Case) -> None:
    (violation,) = case.remove(f"{LINE}/cbc:Percent").violations(RULE)

    assert violation.xpath == f"/ubl:Invoice/{LINE}"
    assert violation.message.endswith("stated in the rate (BT-152); found no rate.")
