"""SRB-002: VAT is accounted in dinars."""

from __future__ import annotations

from einvoice_core.srb.rules.srb_002_vat_accounting_currency import RULE

from .conftest import Case

TAX_CURRENCY = "<cbc:TaxCurrencyCode>RSD</cbc:TaxCurrencyCode>"


def test_satisfied_by_a_dinar_invoice(case: Case) -> None:
    assert case.violations(RULE) == []


def test_satisfied_by_a_euro_invoice_with_vat_in_dinars(case: Case) -> None:
    case.set_text("cbc:DocumentCurrencyCode", "EUR")
    case.insert(".", TAX_CURRENCY, after="cbc:DocumentCurrencyCode")

    assert case.violations(RULE) == []


def test_broken_by_a_euro_invoice_without_a_vat_accounting_currency(case: Case) -> None:
    (violation,) = case.set_text("cbc:DocumentCurrencyCode", "EUR").violations(RULE)

    assert violation.xpath == "/ubl:Invoice"
    assert "must state RSD as the VAT accounting currency (BT-6)" in violation.message


def test_broken_by_vat_accounted_in_euro(case: Case) -> None:
    case.insert(".", TAX_CURRENCY.replace("RSD", "EUR"), after="cbc:DocumentCurrencyCode")

    (violation,) = case.violations(RULE)

    assert violation.xpath == "/ubl:Invoice/cbc:TaxCurrencyCode"
    assert "must be RSD, not 'EUR'" in violation.message
