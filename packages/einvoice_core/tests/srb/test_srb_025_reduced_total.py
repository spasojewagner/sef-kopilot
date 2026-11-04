"""SRB-025: the reduced total with VAT is the total with VAT minus the paid amount."""

from __future__ import annotations

from einvoice_core.srb.rules.srb_025_reduced_total import RULE

from .conftest import Case, settle_advance

EXTENSION = "ext:UBLExtensions/ext:UBLExtension/ext:ExtensionContent/sbt:SrbDtExt"
REDUCED = f"{EXTENSION}/sbt:ReducedTotals"


def test_satisfied_by_a_final_invoice(final_invoice: Case) -> None:
    assert final_invoice.violations(RULE) == []


def test_satisfied_by_an_invoice_without_the_extension(case: Case) -> None:
    assert case.violations(RULE) == []


def test_satisfied_without_a_paid_amount_when_nothing_is_deducted(case: Case) -> None:
    case = settle_advance(case, reduced_total="14400.00")
    case.remove("cac:LegalMonetaryTotal/cbc:PrepaidAmount")

    assert case.violations(RULE) == []


def test_satisfied_when_the_total_with_vat_is_missing(final_invoice: Case) -> None:
    """BT-112 is mandatory; EN 16931 reports its absence, this rule has nothing to compare."""
    final_invoice.remove("cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount")

    assert final_invoice.violations(RULE) == []


def test_broken_by_a_wrong_reduced_total(case: Case) -> None:
    (violation,) = settle_advance(case, reduced_total="9000.00").violations(RULE)

    assert (
        violation.xpath == f"/ubl:Invoice/{REDUCED}/cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount"
    )
    assert violation.message.endswith(
        "minus the paid amount (BT-113): 14400.00 - 6000.00 = 8400.00; found 9000.00."
    )


def test_broken_by_a_reduced_total_that_is_not_an_amount(case: Case) -> None:
    (violation,) = settle_advance(case, reduced_total="8.400,00").violations(RULE)

    assert violation.message.endswith("must be an amount; found '8.400,00'.")


def test_broken_by_reduced_totals_without_the_reduced_total(final_invoice: Case) -> None:
    final_invoice.remove(f"{REDUCED}/cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount")

    (violation,) = final_invoice.violations(RULE)

    assert violation.xpath == f"/ubl:Invoice/{REDUCED}"
    assert "must give the reduced total with VAT (BT-E13)" in violation.message
