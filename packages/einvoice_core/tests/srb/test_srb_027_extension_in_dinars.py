"""SRB-027: on a foreign-currency invoice the extension's VAT breakdowns are also in RSD."""

from __future__ import annotations

from einvoice_core.srb.rules.srb_027_extension_in_dinars import RULE

from .conftest import Case, settle_advance


def test_satisfied_by_a_final_invoice_in_dinars(final_invoice: Case) -> None:
    assert final_invoice.violations(RULE) == []


def test_satisfied_by_a_foreign_currency_invoice_with_rsd_breakdowns(case: Case) -> None:
    case = settle_advance(case, currencies=("EUR", "RSD"))

    assert case.set_text("cbc:DocumentCurrencyCode", "EUR").violations(RULE) == []


def test_satisfied_by_a_foreign_currency_invoice_without_the_extension(case: Case) -> None:
    assert case.set_text("cbc:DocumentCurrencyCode", "EUR").violations(RULE) == []


def test_broken_by_breakdowns_in_the_invoice_currency_only(case: Case) -> None:
    case = settle_advance(case, currencies=("EUR",)).set_text("cbc:DocumentCurrencyCode", "EUR")

    advance, reduced = case.violations(RULE)

    assert advance.xpath is not None
    assert advance.xpath.endswith("/sbt:SrbDtExt/sbt:InvoicedPrepaymentAmount")
    assert "the advance used (BG-E1) must also give its VAT breakdown in RSD (BG-E5)" in (
        advance.message
    )
    assert "the reduced totals (BG-E3) must also give its VAT breakdown in RSD (BG-E6)" in (
        reduced.message
    )
