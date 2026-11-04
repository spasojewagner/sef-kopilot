"""SRB-025: the reduced total with VAT is the total with VAT minus the paid amount (BT-E13).

A final invoice that settles advances states, in the Serbian extension, its totals reduced by
the advances used (BG-E4). SRB-CIUS fixes one of them: the reduced total with VAT (BT-E13)
must equal the invoice total with VAT (BT-112) minus the paid amount (BT-113), which on a
final invoice is the sum of the advance payments. The check is exact decimal arithmetic in the
invoice currency, like every arithmetic check of the validator.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

from einvoice_core.srb.extension import REDUCED_TOTALS, amount
from einvoice_core.srb.rule import Document, Finding, Reference, Rule

REDUCED_TOTAL = "cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount"


def check(document: Document) -> Iterator[Finding]:
    totals = document.invoice.totals
    for reduced in document.find_all(REDUCED_TOTALS):
        element = document.find(REDUCED_TOTAL, reduced)
        text = document.text(REDUCED_TOTAL, reduced)
        if element is None or text is None:
            yield Finding(
                "The reduced totals (BG-E4) must give the reduced total with VAT (BT-E13).",
                reduced,
            )
            continue
        value = amount(text)
        if value is None:
            yield Finding(
                f"The reduced total with VAT (BT-E13) must be an amount; found {text!r}.",
                element,
            )
            continue
        if totals.tax_inclusive_amount is None:
            continue  # BT-112 is mandatory; EN 16931 reports its absence
        paid = totals.prepaid_amount or Decimal(0)
        expected = totals.tax_inclusive_amount - paid
        if value != expected:
            yield Finding(
                "The reduced total with VAT (BT-E13) must equal the total with VAT (BT-112) "
                f"minus the paid amount (BT-113): {totals.tax_inclusive_amount} - {paid} = "
                f"{expected}; found {value}.",
                element,
            )


RULE = Rule(
    id="SRB-025",
    title="The reduced total with VAT is the total with VAT minus the paid amount",
    terms=("BT-E13", "BT-112", "BT-113"),
    references=(Reference("srb-cius", "1.4, Table 2, BT-E13"),),
    check=check,
)
