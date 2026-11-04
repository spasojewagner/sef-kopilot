"""The Serbian extension of SRB-CIUS (1.4, Table 2): where its parts are, and its amounts.

Final invoices that settle earlier advance payments, and invoices in a foreign currency, need
elements the EN 16931 model does not have. SRB-CIUS carries them in ``ext:UBLExtensions`` under
``sbt:SrbDtExt``: the advances used (BG-E1) with their VAT breakdown (BG-E2, and in RSD BG-E5),
and the totals reduced by them (BG-E3, BG-E4, and in RSD BG-E6). The UBL schema does not
validate extension content, so a rule cannot assume that an amount there is a number.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

from lxml import etree

from einvoice_core import numbers
from einvoice_core.srb.rule import Document

__all__ = ["ADVANCES", "DINAR", "EXTENSION", "REDUCED_TOTALS", "amount", "has_breakdown_in"]

#: The Serbian extension element (SrbDtExt).
EXTENSION: Final = "ext:UBLExtensions/ext:UBLExtension/ext:ExtensionContent/sbt:SrbDtExt"
#: The advances used (BG-E1). The specification spells the element InvoicedPrepaymentAmmount,
#: the Ministry's examples InvoicedPrepaymentAmount; both are recognised.
ADVANCES: Final = (
    f"{EXTENSION}/sbt:InvoicedPrepaymentAmount | {EXTENSION}/sbt:InvoicedPrepaymentAmmount"
)
#: The totals reduced by the advances used (BG-E3, BG-E4, BG-E6).
REDUCED_TOTALS: Final = f"{EXTENSION}/sbt:ReducedTotals"
#: The currency in which VAT is always accounted (SRB-CIUS 1.4).
DINAR: Final = "RSD"


def amount(text: str | None) -> Decimal | None:
    """``text`` as an amount, or ``None`` if it is absent, not in the form of ``xs:decimal``, or
    longer than the checks can compute with exactly (:mod:`einvoice_core.numbers`)."""
    return numbers.parse(text)


def has_breakdown_in(document: Document, parent: etree._Element, currency: str) -> bool:
    """Whether ``parent`` has a ``TaxTotal`` in ``currency`` with at least one subtotal."""
    for total in document.find_all("cac:TaxTotal", parent):
        tax_amount = document.find("cbc:TaxAmount", total)
        in_currency = tax_amount is not None and tax_amount.get("currencyID") == currency
        if in_currency and document.find_all("cac:TaxSubtotal", total):
            return True
    return False
