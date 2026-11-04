"""SRB-028: a foreign-currency invoice gives its VAT breakdown in RSD as well."""

from __future__ import annotations

from einvoice_core.srb.rules.srb_028_vat_breakdown_in_dinars import RULE

from .conftest import Case, vat_total


def test_satisfied_by_an_invoice_in_dinars(case: Case) -> None:
    assert case.violations(RULE) == []


def test_satisfied_by_a_foreign_currency_invoice_with_the_rsd_breakdown(
    credit_note: Case,
) -> None:
    credit_note.remove("cac:TaxTotal[2]")
    credit_note.insert(".", vat_total("RSD", "106080.00", "21216.00"), after="cac:TaxTotal")

    assert credit_note.violations(RULE) == []


def test_broken_by_an_rsd_vat_total_without_subtotals(credit_note: Case) -> None:
    """The synthetic credit note follows EN 16931: in RSD only the VAT total (BT-111)."""
    (violation,) = credit_note.violations(RULE)

    assert violation.xpath == "/cn:CreditNote/cac:TaxTotal[2]"
    assert violation.message.startswith(
        "[SRB-028]-An invoice in EUR must also give its VAT breakdown in RSD (BG-E7)"
    )


def test_broken_by_no_vat_total_in_dinars_at_all(case: Case) -> None:
    case.set_text("cbc:DocumentCurrencyCode", "EUR")
    case.set_attribute("cac:TaxTotal/cbc:TaxAmount", "currencyID", "EUR")

    (violation,) = case.violations(RULE)

    assert violation.xpath == "/ubl:Invoice"
