"""SRB-004: an advance invoice has a payment due date."""

from __future__ import annotations

from einvoice_core.srb.rules.srb_004_advance_invoice_due_date import RULE

from .conftest import Case


def test_satisfied_by_an_advance_invoice_with_a_due_date(case: Case) -> None:
    assert case.set_text("cbc:InvoiceTypeCode", "386").violations(RULE) == []


def test_satisfied_by_a_commercial_invoice_without_a_due_date(case: Case) -> None:
    assert case.remove("cbc:DueDate").violations(RULE) == []


def test_broken_by_an_advance_invoice_without_a_due_date(case: Case) -> None:
    case.set_text("cbc:InvoiceTypeCode", "386").remove("cbc:DueDate")

    (violation,) = case.violations(RULE)

    assert violation.xpath == "/ubl:Invoice"
    assert "payment due date (BT-9)" in violation.message
