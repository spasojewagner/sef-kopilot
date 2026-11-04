"""SRB-011: a preceding invoice reference gives the preceding invoice's issue date."""

from __future__ import annotations

from einvoice_core.srb.rules.srb_011_preceding_invoice_issue_date import RULE

from .conftest import Case

REFERENCE = (
    "<cac:BillingReference><cac:InvoiceDocumentReference>"
    "<cbc:ID>RF-2026-000100</cbc:ID>{issue_date}"
    "</cac:InvoiceDocumentReference></cac:BillingReference>"
)


def with_reference(case: Case, issue_date: str) -> Case:
    fragment = REFERENCE.format(issue_date=issue_date)
    return case.insert(".", fragment, after="cac:InvoicePeriod")


def test_satisfied_without_a_preceding_invoice(case: Case) -> None:
    assert case.violations(RULE) == []


def test_satisfied_by_a_reference_with_number_and_date(case: Case) -> None:
    case = with_reference(case, "<cbc:IssueDate>2026-09-30</cbc:IssueDate>")

    assert case.violations(RULE) == []


def test_broken_by_a_reference_without_the_date(case: Case) -> None:
    (violation,) = with_reference(case, "").violations(RULE)

    assert violation.xpath == "/ubl:Invoice/cac:BillingReference/cac:InvoiceDocumentReference"
    assert "'RF-2026-000100' (BG-3) must give that invoice's issue date" in violation.message
