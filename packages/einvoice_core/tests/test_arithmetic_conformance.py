"""The Python BR-CO rules report exactly what CEN's EN 16931 XSLT reports.

A differential test: Hypothesis generates the money part of an invoice — lines, document
level allowances and charges, VAT totals and document totals, consistent or with one amount
changed or left out, with two or three decimals so that rounding is exercised — and both
layers judge the same document. For BR-CO-10 to BR-CO-17 they must report the same rules the
same number of times.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from einvoice_core.arithmetic import RULE_IDS, cents, validate_arithmetic
from einvoice_core.rulesets import RulesetNotFoundError, ruleset_path
from einvoice_core.schematron import validate_schematron
from einvoice_core.xml import load_document

from .conftest import SYNTHETIC_DIR


def _fetched() -> bool:
    try:
        ruleset_path("en16931")
    except RulesetNotFoundError:
        return False
    return True


pytestmark = [
    pytest.mark.conformance,
    pytest.mark.skipif(not _fetched(), reason="rule sets not fetched (run `make rulesets`)"),
]

TEMPLATE = (SYNTHETIC_DIR / "srb-minimal-invoice.xml").read_text(encoding="utf-8")
HEAD = TEMPLATE[: TEMPLATE.index("  <cac:TaxTotal>")]
ZERO = Decimal(0)

amounts = st.one_of(
    st.decimals(min_value=-50, max_value=5000, places=2, allow_nan=False),
    st.decimals(min_value=-50, max_value=5000, places=3, allow_nan=False),
)
deltas = st.sampled_from(
    [Decimal(d) for d in ("0.01", "-0.01", "0.004", "0.005", "-0.005", "0.99", "1", "1.01", "-2")]
)


def money(value: Decimal) -> str:
    return f'currencyID="RSD">{value:f}'


@dataclass(frozen=True)
class Totals:
    """The amounts of a generated invoice; ``None`` leaves an optional element out."""

    lines: tuple[Decimal, ...]
    allowances: tuple[Decimal, ...]
    charges: tuple[Decimal, ...]
    rate: Decimal
    scheme: str
    line_extension: Decimal | None
    allowance_total: Decimal | None
    charge_total: Decimal | None
    tax_exclusive: Decimal | None
    tax_amount: Decimal
    taxable: Decimal | None
    subtotal_tax: Decimal
    tax_inclusive: Decimal | None
    prepaid: Decimal | None
    rounding: Decimal | None
    payable: Decimal
    extra_total: str | None

    def xml(self) -> str:
        def optional(name: str, value: Decimal | None) -> str:
            return "" if value is None else f"<cbc:{name} {money(value)}</cbc:{name}>"

        category = (
            f"<cac:TaxCategory><cbc:ID>S</cbc:ID><cbc:Percent>{self.rate:f}</cbc:Percent>"
            f"<cac:TaxScheme><cbc:ID>{self.scheme}</cbc:ID></cac:TaxScheme></cac:TaxCategory>"
        )
        allowances_charges = "".join(
            f"<cac:AllowanceCharge><cbc:ChargeIndicator>{indicator}</cbc:ChargeIndicator>"
            f"<cbc:AllowanceChargeReason>Razlog</cbc:AllowanceChargeReason>"
            f"<cbc:Amount {money(amount)}</cbc:Amount>{category}</cac:AllowanceCharge>"
            for indicator, items in (("false", self.allowances), ("true", self.charges))
            for amount in items
        )
        subtotal = (
            f"<cac:TaxSubtotal>{optional('TaxableAmount', self.taxable)}"
            f"<cbc:TaxAmount {money(self.subtotal_tax)}</cbc:TaxAmount>{category}</cac:TaxSubtotal>"
        )
        tax_total = f"<cac:TaxTotal><cbc:TaxAmount {money(self.tax_amount)}</cbc:TaxAmount>"
        tax_totals = f"{tax_total}{subtotal}</cac:TaxTotal>"
        if self.extra_total == "same":
            tax_totals += f"{tax_total}</cac:TaxTotal>"
        elif self.extra_total == "other":
            tax_totals += '<cac:TaxTotal><cbc:TaxAmount currencyID="EUR">1.00</cbc:TaxAmount>'
            tax_totals += "</cac:TaxTotal>"
        totals = (
            "<cac:LegalMonetaryTotal>"
            + optional("LineExtensionAmount", self.line_extension)
            + optional("TaxExclusiveAmount", self.tax_exclusive)
            + optional("TaxInclusiveAmount", self.tax_inclusive)
            + optional("AllowanceTotalAmount", self.allowance_total)
            + optional("ChargeTotalAmount", self.charge_total)
            + optional("PrepaidAmount", self.prepaid)
            + optional("PayableRoundingAmount", self.rounding)
            + f"<cbc:PayableAmount {money(self.payable)}</cbc:PayableAmount>"
            + "</cac:LegalMonetaryTotal>"
        )
        lines = "".join(
            f"<cac:InvoiceLine><cbc:ID>{number}</cbc:ID>"
            f'<cbc:InvoicedQuantity unitCode="H87">1</cbc:InvoicedQuantity>'
            f"<cbc:LineExtensionAmount {money(amount)}</cbc:LineExtensionAmount>"
            f"<cac:Item><cbc:Name>Stavka</cbc:Name>"
            f"{category.replace('TaxCategory', 'ClassifiedTaxCategory')}</cac:Item>"
            f"<cac:Price><cbc:PriceAmount {money(amount)}</cbc:PriceAmount></cac:Price>"
            "</cac:InvoiceLine>"
            for number, amount in enumerate(self.lines, 1)
        )
        return f"{HEAD}{allowances_charges}{tax_totals}{totals}{lines}\n</Invoice>\n"


@st.composite
def invoices(draw: st.DrawFn) -> Totals:
    """A consistent set of amounts, then at most one amount changed or left out."""
    lines = tuple(draw(st.lists(amounts, min_size=1, max_size=3)))
    allowances = tuple(draw(st.lists(amounts, max_size=2)))
    charges = tuple(draw(st.lists(amounts, max_size=2)))
    rate = draw(st.sampled_from([Decimal(r) for r in ("20", "10", "0", "0.4")]))
    line_sum = cents(sum(lines, ZERO))
    allowance_sum = cents(sum(allowances, ZERO)) if allowances else None
    charge_sum = cents(sum(charges, ZERO)) if charges else None
    without_vat = cents(line_sum - (allowance_sum or ZERO) + (charge_sum or ZERO))
    tax = cents(without_vat * rate / 100)
    with_vat = cents(without_vat + tax)
    prepaid = draw(st.one_of(st.none(), amounts))
    rounding = draw(st.one_of(st.none(), st.sampled_from([Decimal("0.01"), Decimal("-0.02")])))
    totals = Totals(
        lines=lines,
        allowances=allowances,
        charges=charges,
        rate=rate,
        scheme=draw(st.sampled_from(["VAT", "VAT", "VAT", " vat ", "GST"])),
        line_extension=line_sum,
        allowance_total=allowance_sum,
        charge_total=charge_sum,
        tax_exclusive=without_vat,
        tax_amount=tax,
        taxable=without_vat,
        subtotal_tax=tax,
        tax_inclusive=with_vat,
        prepaid=prepaid,
        rounding=rounding,
        payable=with_vat - (prepaid or ZERO) + (rounding or ZERO),
        extra_total=draw(st.sampled_from([None, None, None, "same", "other"])),
    )
    field = draw(
        st.sampled_from(
            [
                None,
                "line_extension",
                "allowance_total",
                "charge_total",
                "tax_exclusive",
                "tax_amount",
                "taxable",
                "subtotal_tax",
                "tax_inclusive",
                "payable",
            ]
        )
    )
    if field is None:
        return totals
    change: dict[str, Any] = {field: None}
    if field in ("tax_amount", "subtotal_tax", "payable") or draw(st.booleans()):
        change[field] = (getattr(totals, field) or ZERO) + draw(deltas)
    return replace(totals, **change)


@settings(max_examples=400, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(invoices())
def test_python_and_cen_report_the_same_calculation_rules(totals: Totals) -> None:
    tree = load_document(totals.xml().encode("utf-8"))

    ours = Counter(violation.rule_id for violation in validate_arithmetic(tree))
    cens = Counter(
        violation.rule_id
        for violation in validate_schematron(tree, ["en16931"])
        if violation.rule_id in RULE_IDS
    )

    assert ours == cens
