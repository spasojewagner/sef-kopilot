"""EN 16931 calculation rules BR-CO-10 to BR-CO-17, computed in Python (ADR-0007).

The Schematron layer runs these rules as CEN publishes them. This layer computes them again,
from the typed model and with exact decimal arithmetic, because:

* a violation can state the expected value next to the one found, computed by code, so that
  no explanation ever has to do arithmetic (ADR-0002);
* it reads exactly the business terms the model holds: the document totals (BG-22), the VAT
  totals of the document and the invoice lines. CEN's rule contexts also match the totals that
  the Serbian extension repeats inside ``ext:UBLExtensions``, which are not BG-22;
* the repair loop can re-check amounts without running an XSLT.

The semantics are CEN's, including their rounding and tolerance: amounts are compared after
``round(x * 10 * 10) div 100`` with XPath's ``round()`` (half towards positive infinity), and
BR-CO-17 accepts a VAT amount within one currency unit of the computed one. A differential test
checks that this layer and CEN's XSLT report the same rules on generated invoices.
"""

from __future__ import annotations

from decimal import ROUND_FLOOR, Decimal
from typing import Final

from lxml import etree

from einvoice_core import model
from einvoice_core.numbers import exact
from einvoice_core.ubl import build_invoice
from einvoice_core.violations import Severity, Violation
from einvoice_core.xml import NAMESPACES

__all__ = ["RULE_IDS", "cents", "validate_arithmetic", "xpath_round"]

#: CEN's statement of each rule, used as the start of its message.
STATEMENTS: Final[dict[str, str]] = {
    "BR-CO-10": "Sum of Invoice line net amount (BT-106) = Σ Invoice line net amount (BT-131)",
    "BR-CO-11": (
        "Sum of allowances on document level (BT-107) = Σ Document level allowance amount (BT-92)"
    ),
    "BR-CO-12": (
        "Sum of charges on document level (BT-108) = Σ Document level charge amount (BT-99)"
    ),
    "BR-CO-13": (
        "Invoice total amount without VAT (BT-109) = Σ Invoice line net amount (BT-131) - Sum of "
        "allowances on document level (BT-107) + Sum of charges on document level (BT-108)"
    ),
    "BR-CO-14": "Invoice total VAT amount (BT-110) = Σ VAT category tax amount (BT-117)",
    "BR-CO-15": (
        "Invoice total amount with VAT (BT-112) = Invoice total amount without VAT (BT-109) + "
        "Invoice total VAT amount (BT-110)"
    ),
    "BR-CO-16": (
        "Amount due for payment (BT-115) = Invoice total amount with VAT (BT-112) - Paid amount "
        "(BT-113) + Rounding amount (BT-114)"
    ),
    "BR-CO-17": (
        "VAT category tax amount (BT-117) = VAT category taxable amount (BT-116) x (VAT category "
        "rate (BT-119) / 100), rounded to two decimals"
    ),
}
#: The rules this layer computes, in the order it reports them.
RULE_IDS: Final = tuple(STATEMENTS)

_HALF: Final = Decimal("0.5")
_HUNDRED: Final = Decimal(100)
_CENT: Final = Decimal("0.01")


def xpath_round(value: Decimal) -> Decimal:
    """XPath 2.0 ``fn:round``: the nearest integer, halves towards positive infinity."""
    return (value + _HALF).to_integral_value(rounding=ROUND_FLOOR)


def cents(value: Decimal) -> Decimal:
    """CEN's ``round(x * 10 * 10) div 100``: ``value`` rounded to two decimals."""
    return (xpath_round(value * _HUNDRED) / _HUNDRED).quantize(_CENT)


def _shown(value: Decimal | None) -> str:
    return "nothing" if value is None else str(value)


class _Report:
    """Collects violations, locating each one in the tree."""

    def __init__(self, tree: etree._ElementTree) -> None:
        self._root = tree.getroot()
        self.violations: list[Violation] = []

    def add(self, rule_id: str, detail: str, xpath: str) -> None:
        found = self._root.xpath(xpath, namespaces=NAMESPACES)
        element = found[0] if isinstance(found, list) and found else None
        line = element.sourceline if isinstance(element, etree._Element) else None
        self.violations.append(
            Violation(
                rule_id=rule_id,
                severity=Severity.FATAL,
                message=f"[{rule_id}]-{STATEMENTS[rule_id]}: {detail}",
                xpath=xpath,
                layer="arithmetic",
                line=line,
            )
        )


def _child(group_xpath: str, name: str, value: Decimal | None) -> str:
    """The XPath of an amount in a group, or of the group when the amount is absent."""
    return group_xpath if value is None else f"{group_xpath}/{name}"


def _line_and_allowance_totals(invoice: model.Invoice, report: _Report) -> None:
    totals = invoice.totals
    line_sum = cents(sum((line.net_amount for line in invoice.lines), Decimal(0)))
    if totals.line_extension_amount != line_sum:
        report.add(
            "BR-CO-10",
            f"expected {line_sum}, found {_shown(totals.line_extension_amount)}.",
            _child(totals.xpath, "cbc:LineExtensionAmount", totals.line_extension_amount),
        )
    for rule_id, is_charge, found, name in (
        ("BR-CO-11", False, totals.allowance_total_amount, "cbc:AllowanceTotalAmount"),
        ("BR-CO-12", True, totals.charge_total_amount, "cbc:ChargeTotalAmount"),
    ):
        amounts = [
            item.amount for item in invoice.allowances_charges if item.is_charge is is_charge
        ]
        expected = cents(sum(amounts, Decimal(0)))
        if (found is None and amounts) or (found is not None and found != expected):
            report.add(
                rule_id,
                f"expected {expected}, found {_shown(found)}.",
                _child(totals.xpath, name, found),
            )


def _total_without_vat(invoice: model.Invoice, report: _Report) -> None:
    totals = invoice.totals
    lines, allowances, charges = (
        totals.line_extension_amount,
        totals.allowance_total_amount,
        totals.charge_total_amount,
    )
    found = totals.tax_exclusive_amount
    if lines is None:
        expected: Decimal | None = None
    elif allowances is None and charges is None:
        expected = lines
    else:
        expected = cents(lines - (allowances or Decimal(0)) + (charges or Decimal(0)))
    if found is None or expected is None or found != expected:
        report.add(
            "BR-CO-13",
            f"expected {_shown(expected)}, found {_shown(found)}.",
            _child(totals.xpath, "cbc:TaxExclusiveAmount", found),
        )


def _vat_totals(invoice: model.Invoice, report: _Report) -> None:
    for total in invoice.tax_totals:
        if not total.breakdown:
            continue
        expected = cents(sum((entry.tax_amount for entry in total.breakdown), Decimal(0)))
        if total.tax_amount != expected:
            report.add(
                "BR-CO-14",
                f"expected {expected}, found {total.tax_amount}.",
                f"{total.xpath}/cbc:TaxAmount",
            )


def _total_with_vat(invoice: model.Invoice, report: _Report) -> None:
    if invoice.currency is None:
        return  # CEN's rule quantifies over the invoice currency code: nothing to check
    totals = invoice.totals
    vat = [total.tax_amount for total in invoice.tax_totals if total.currency == invoice.currency]
    found = totals.tax_inclusive_amount
    if len(vat) != 1:
        report.add(
            "BR-CO-15",
            f"the invoice needs exactly one VAT total in {invoice.currency}, found {len(vat)}.",
            invoice.xpath,
        )
        return
    without_vat = totals.tax_exclusive_amount
    expected = None if without_vat is None else cents(without_vat + vat[0])
    if found is None or expected is None or found != expected:
        report.add(
            "BR-CO-15",
            f"expected {_shown(expected)}, found {_shown(found)}.",
            _child(totals.xpath, "cbc:TaxInclusiveAmount", found),
        )


def _amount_due(invoice: model.Invoice, report: _Report) -> None:
    totals = invoice.totals
    with_vat, paid, rounding = (
        totals.tax_inclusive_amount,
        totals.prepaid_amount,
        totals.payable_rounding_amount,
    )
    due = totals.payable_amount
    xpath = f"{totals.xpath}/cbc:PayableAmount"
    if with_vat is None:
        report.add("BR-CO-16", f"nothing to compare with, found {due}.", xpath)
        return
    expected = with_vat if paid is None else cents(with_vat - paid)
    compared = due if rounding is None else cents(due - rounding)
    if compared != expected:
        detail = f"expected {cents(expected + rounding) if rounding is not None else expected}"
        report.add("BR-CO-16", f"{detail}, found {due}.", xpath)


def _vat_amounts(invoice: model.Invoice, report: _Report) -> None:
    for total in invoice.tax_totals:
        for entry in total.breakdown:
            vat_scheme = (entry.tax_scheme or "").strip().upper() == "VAT"
            rate = entry.rate if vat_scheme else None
            tax, taxable = entry.tax_amount, entry.taxable_amount
            if rate is None or xpath_round(rate) == 0:
                if xpath_round(tax) != 0:
                    condition = "without a VAT rate" if rate is None else f"at the rate {rate}"
                    report.add(
                        "BR-CO-17",
                        f"{condition} the tax amount must round to 0, found {tax}.",
                        f"{entry.xpath}/cbc:TaxAmount",
                    )
                continue
            computed = None if taxable is None else cents(abs(taxable) * (rate / _HUNDRED))
            if computed is None or not (abs(tax) - 1 < computed < abs(tax) + 1):
                report.add(
                    "BR-CO-17",
                    f"{_shown(taxable)} x {rate} / 100 = {_shown(computed)} (within one currency "
                    f"unit), found {tax}.",
                    f"{entry.xpath}/cbc:TaxAmount",
                )


def validate_arithmetic(
    tree: etree._ElementTree, invoice: model.Invoice | None = None
) -> tuple[Violation, ...]:
    """The BR-CO calculation violations of a schema-valid document.

    ``invoice`` is the model of ``tree`` when the caller has already built it; otherwise it is
    built here (which raises :class:`einvoice_core.xml.ParseError` for a document the model
    cannot represent).
    """
    invoice = invoice or build_invoice(tree.getroot())
    report = _Report(tree)
    with exact():
        _line_and_allowance_totals(invoice, report)
        _total_without_vat(invoice, report)
        _vat_totals(invoice, report)
        _total_with_vat(invoice, report)
        _amount_due(invoice, report)
        _vat_amounts(invoice, report)
    return tuple(report.violations)
