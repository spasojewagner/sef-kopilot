"""SRB-018: the actual delivery date is given when VAT is due on supply or on collection."""

from __future__ import annotations

import pytest

from einvoice_core.srb.rules.srb_018_actual_delivery_date import RULE

from .conftest import Case

CODE = "cac:InvoicePeriod/cbc:DescriptionCode"
DELIVERY = "cac:Delivery"


def test_satisfied_by_a_delivery_date_with_code_35(case: Case) -> None:
    assert case.violations(RULE) == []


@pytest.mark.parametrize("code", ["3", "432"])
def test_satisfied_without_a_delivery_date_when_vat_is_not_due_on_supply(
    case: Case, code: str
) -> None:
    """3: due on the issue date; 432 on an advance invoice: due on the payment date."""
    case.set_text(CODE, code).set_text("cbc:InvoiceTypeCode", "386").remove(DELIVERY)

    assert case.violations(RULE) == []


def test_satisfied_without_a_vat_point_date_code(case: Case) -> None:
    assert case.remove("cac:InvoicePeriod").remove(DELIVERY).violations(RULE) == []


def test_broken_by_code_35_without_a_delivery_date(case: Case) -> None:
    (violation,) = case.remove(DELIVERY).violations(RULE)

    assert violation.xpath == f"/ubl:Invoice/{CODE}"
    assert "BT-8) 35, VAT is due on the date of supply" in violation.message


def test_broken_by_cash_accounting_without_a_delivery_date(case: Case) -> None:
    (violation,) = case.set_text(CODE, "432").remove(DELIVERY).violations(RULE)

    assert "VAT is due on collection (cash accounting)" in violation.message
