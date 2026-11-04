"""BR-CO-10 to BR-CO-17 in Python: CEN's semantics, with the computation in the message."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from einvoice_core.arithmetic import RULE_IDS, cents, validate_arithmetic, xpath_round
from einvoice_core.violations import Severity, Violation
from einvoice_core.xml import load_document

from .conftest import SYNTHETIC_DIR

INVOICE = (SYNTHETIC_DIR / "srb-minimal-invoice.xml").read_text(encoding="utf-8")
CREDIT_NOTE = (SYNTHETIC_DIR / "credit-note-full.xml").read_text(encoding="utf-8")
TOTALS = "/ubl:Invoice/cac:LegalMonetaryTotal"


def violations(source: str, *edits: tuple[str, str], rule: str | None = None) -> list[Violation]:
    for old, new in edits:
        assert old in source, old
        source = source.replace(old, new, 1)
    found = validate_arithmetic(load_document(source.encode("utf-8")))
    return [violation for violation in found if rule is None or violation.rule_id == rule]


def amount(name: str, value: str, currency: str = "RSD") -> str:
    return f'<cbc:{name} currencyID="{currency}">{value}</cbc:{name}>'


@pytest.mark.parametrize(
    ("value", "rounded"),
    [("2.5", "3"), ("-2.5", "-2"), ("2.4", "2"), ("-2.6", "-3"), ("0", "0")],
)
def test_xpath_round_takes_halves_towards_positive_infinity(value: str, rounded: str) -> None:
    assert xpath_round(Decimal(value)) == Decimal(rounded)


@pytest.mark.parametrize(
    ("value", "rounded"), [("0.125", "0.13"), ("-0.125", "-0.12"), ("10.004", "10.00")]
)
def test_cents_rounds_to_two_decimals_like_cen(value: str, rounded: str) -> None:
    assert cents(Decimal(value)) == Decimal(rounded)


@pytest.mark.parametrize("path", sorted(SYNTHETIC_DIR.glob("*.xml")), ids=lambda path: path.name)
def test_the_synthetic_fixtures_add_up(path: Path) -> None:
    assert validate_arithmetic(load_document(path)) == ()


def test_a_wrong_line_total_is_reported_with_the_computation() -> None:
    (violation,) = violations(
        INVOICE,
        (amount("LineExtensionAmount", "12000.00"), amount("LineExtensionAmount", "12000.01")),
        rule="BR-CO-10",
    )

    assert violation.severity is Severity.FATAL
    assert violation.layer == "arithmetic"
    assert violation.xpath == f"{TOTALS}/cbc:LineExtensionAmount"
    assert violation.line is not None
    assert violation.message == (
        "[BR-CO-10]-Sum of Invoice line net amount (BT-106) = Σ Invoice line net amount "
        "(BT-131): expected 12000.00, found 12000.01."
    )


def test_a_missing_line_total_is_reported_on_the_totals() -> None:
    edit = (amount("LineExtensionAmount", "12000.00"), "")
    by_rule = {violation.rule_id: violation for violation in violations(INVOICE, edit)}

    assert set(by_rule) == {"BR-CO-10", "BR-CO-13"}
    assert by_rule["BR-CO-10"].xpath == TOTALS
    assert by_rule["BR-CO-10"].message.endswith("expected 12000.00, found nothing.")
    assert by_rule["BR-CO-13"].message.endswith("expected nothing, found 12000.00.")


@pytest.mark.parametrize(
    ("element", "rule"), [("AllowanceTotalAmount", "BR-CO-11"), ("ChargeTotalAmount", "BR-CO-12")]
)
def test_allowance_and_charge_totals(element: str, rule: str) -> None:
    original = amount(element, "100.00" if rule == "BR-CO-11" else "25.00", "EUR")

    (changed,) = violations(CREDIT_NOTE, (original, amount(element, "99.00", "EUR")), rule=rule)
    (missing,) = violations(CREDIT_NOTE, (original, ""), rule=rule)

    assert changed.xpath == f"/cn:CreditNote/cac:LegalMonetaryTotal/cbc:{element}"
    assert changed.message.endswith("found 99.00.")
    assert missing.xpath == "/cn:CreditNote/cac:LegalMonetaryTotal"
    assert missing.message.endswith("found nothing.")


def test_a_total_of_allowances_without_allowances_must_be_zero() -> None:
    edit = (
        amount("TaxExclusiveAmount", "12000.00"),
        amount("TaxExclusiveAmount", "12000.00") + amount("AllowanceTotalAmount", "5.00"),
    )

    assert [v.rule_id for v in violations(INVOICE, edit)] == ["BR-CO-11", "BR-CO-13"]


def test_the_total_without_vat_follows_lines_allowances_and_charges() -> None:
    (violation,) = violations(
        CREDIT_NOTE,
        (
            amount("TaxExclusiveAmount", "925.00", "EUR"),
            amount("TaxExclusiveAmount", "926.00", "EUR"),
        ),
        rule="BR-CO-13",
    )

    assert violation.message.endswith("expected 925.00, found 926.00.")


@pytest.mark.parametrize("remove", ["AllowanceTotalAmount", "ChargeTotalAmount"])
def test_the_total_without_vat_with_one_of_allowances_or_charges(remove: str) -> None:
    value = "100.00" if remove == "AllowanceTotalAmount" else "25.00"
    found = violations(CREDIT_NOTE, (amount(remove, value, "EUR"), ""), rule="BR-CO-13")

    expected = "1025.00" if remove == "AllowanceTotalAmount" else "900.00"
    assert [violation.message.split(": ")[-1] for violation in found] == [
        f"expected {expected}, found 925.00."
    ]


def test_the_vat_total_is_the_sum_of_the_breakdown() -> None:
    (violation,) = violations(
        INVOICE, (amount("TaxAmount", "2400.00"), amount("TaxAmount", "2400.10")), rule="BR-CO-14"
    )

    assert violation.xpath == "/ubl:Invoice/cac:TaxTotal/cbc:TaxAmount"
    assert violation.message.endswith("expected 2400.00, found 2400.10.")


def test_the_total_with_vat_and_the_one_vat_total_in_the_invoice_currency() -> None:
    (wrong,) = violations(
        INVOICE,
        (amount("TaxInclusiveAmount", "14400.00"), amount("TaxInclusiveAmount", "14400.02")),
        rule="BR-CO-15",
    )
    (twice,) = violations(
        INVOICE,
        (
            "  <cac:LegalMonetaryTotal>",
            f"<cac:TaxTotal>{amount('TaxAmount', '0.00')}</cac:TaxTotal>"
            "\n  <cac:LegalMonetaryTotal>",
        ),
        rule="BR-CO-15",
    )

    assert wrong.xpath == f"{TOTALS}/cbc:TaxInclusiveAmount"
    assert wrong.message.endswith("expected 14400.00, found 14400.02.")
    assert twice.xpath == "/ubl:Invoice"
    assert twice.message.endswith("exactly one VAT total in RSD, found 2.")


def test_without_an_invoice_currency_there_is_no_total_with_vat_to_check() -> None:
    edit = ("<cbc:DocumentCurrencyCode>RSD</cbc:DocumentCurrencyCode>", "")

    assert violations(INVOICE, edit, rule="BR-CO-15") == []


def test_the_amount_due_with_paid_and_rounding_amounts() -> None:
    assert violations(CREDIT_NOTE, rule="BR-CO-16") == []
    (violation,) = violations(
        CREDIT_NOTE,
        (amount("PayableAmount", "1100.00", "EUR"), amount("PayableAmount", "1101.00", "EUR")),
        rule="BR-CO-16",
    )

    assert violation.message.endswith("expected 1100.00, found 1101.00.")


def test_the_amount_due_without_a_paid_amount_is_the_total_with_vat() -> None:
    (violation,) = violations(
        INVOICE,
        (amount("PayableAmount", "14400.00"), amount("PayableAmount", "14000.00")),
        rule="BR-CO-16",
    )

    assert violation.xpath == f"{TOTALS}/cbc:PayableAmount"
    assert violation.message.endswith("expected 14400.00, found 14000.00.")


def test_the_amount_due_without_a_total_with_vat() -> None:
    edit = (amount("TaxInclusiveAmount", "14400.00"), "")

    (violation,) = violations(INVOICE, edit, rule="BR-CO-16")

    assert violation.message.endswith("nothing to compare with, found 14400.00.")


@pytest.mark.parametrize(("tax", "reported"), [("2400.99", False), ("2401.00", True)])
def test_a_vat_amount_is_accepted_within_one_currency_unit(tax: str, reported: bool) -> None:
    edits = (
        (amount("TaxAmount", "2400.00"), amount("TaxAmount", tax)),
        (amount("TaxAmount", "2400.00"), amount("TaxAmount", tax)),
    )

    found = violations(INVOICE, *edits, rule="BR-CO-17")

    assert bool(found) is reported
    if reported:
        assert found[0].message.endswith(
            "12000.00 x 20 / 100 = 2400.00 (within one currency unit), found 2401.00."
        )


@pytest.mark.parametrize(
    ("percent", "scheme", "condition"),
    [
        ("0", "VAT", "at the rate 0"),
        ("0.4", "VAT", "at the rate 0.4"),
        ("20", "GST", "without a VAT rate"),
    ],
)
def test_without_a_rate_the_vat_amount_must_round_to_zero(
    percent: str, scheme: str, condition: str
) -> None:
    source = INVOICE.replace(
        "<cbc:Percent>20</cbc:Percent>", f"<cbc:Percent>{percent}</cbc:Percent>"
    )
    source = source.replace("<cbc:ID>VAT</cbc:ID>", f"<cbc:ID>{scheme}</cbc:ID>")

    (violation,) = violations(source, rule="BR-CO-17")

    assert violation.message.endswith(f"{condition} the tax amount must round to 0, found 2400.00.")


def test_every_rule_has_a_statement() -> None:
    assert tuple(f"BR-CO-{number}" for number in range(10, 18)) == RULE_IDS
