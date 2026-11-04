"""SRB-026: every advance used names one of the invoice's preceding invoices."""

from __future__ import annotations

from einvoice_core.srb.rules.srb_026_advance_references import RULE
from einvoice_core.xml import SRBDT_EXT

from .conftest import Case, settle_advance

ADVANCE = (
    "ext:UBLExtensions/ext:UBLExtension/ext:ExtensionContent/sbt:SrbDtExt"
    "/sbt:InvoicedPrepaymentAmount"
)


def test_satisfied_by_a_final_invoice(final_invoice: Case) -> None:
    assert final_invoice.violations(RULE) == []


def test_satisfied_by_an_invoice_without_advances(case: Case) -> None:
    assert case.violations(RULE) == []


def test_broken_by_an_advance_that_is_not_a_preceding_invoice(case: Case) -> None:
    (violation,) = settle_advance(case, advance="AV-2026-0008").violations(RULE)

    assert violation.xpath == f"/ubl:Invoice/{ADVANCE}/cbc:ID"
    assert "'AV-2026-0008' used on this invoice (BT-E1) must also be referenced" in (
        violation.message
    )


def test_broken_by_an_advance_without_its_number(final_invoice: Case) -> None:
    (violation,) = final_invoice.remove(f"{ADVANCE}/cbc:ID").violations(RULE)

    assert violation.xpath == f"/ubl:Invoice/{ADVANCE}"
    assert "must give the number of its advance invoice (BT-E1)" in violation.message


def test_broken_also_under_the_specifications_spelling(case: Case) -> None:
    """SRB-CIUS writes InvoicedPrepaymentAmmount, the Ministry's examples one m."""
    case = settle_advance(case, advance="AV-2026-0008")
    case.element(ADVANCE).tag = f"{{{SRBDT_EXT}}}InvoicedPrepaymentAmmount"

    (violation,) = case.violations(RULE)

    assert violation.xpath is not None
    assert violation.xpath.endswith("/sbt:InvoicedPrepaymentAmmount/cbc:ID")
