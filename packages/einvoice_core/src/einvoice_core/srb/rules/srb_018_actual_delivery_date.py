"""SRB-018: the actual delivery date is given when VAT is due on supply or on payment (BT-72).

SRB-CIUS reads the VAT point date code (BT-8) as the rule by which VAT becomes due: 35 by the
date of supply, 3 by the invoice issue date, and 432 by the payment date on an advance invoice
but by cash accounting (on collection) on any other invoice. When VAT is due by the date of
supply or by cash accounting, the actual delivery date (BT-72) is mandatory.
"""

from __future__ import annotations

from collections.abc import Iterator

from einvoice_core.srb.rule import Document, Finding, Reference, Rule

DATE_OF_SUPPLY = "35"
PAID_TO_DATE = "432"
ADVANCE_INVOICE = "386"


def check(document: Document) -> Iterator[Finding]:
    element = document.find("cac:InvoicePeriod/cbc:DescriptionCode")
    code = document.text("cac:InvoicePeriod/cbc:DescriptionCode")
    if element is None or document.text("cac:Delivery/cbc:ActualDeliveryDate") is not None:
        return
    if code == DATE_OF_SUPPLY:
        yield Finding(
            "With the VAT point date code (BT-8) 35, VAT is due on the date of supply, so the "
            "actual delivery date (BT-72) is required.",
            element,
        )
    elif code == PAID_TO_DATE and document.invoice.type_code != ADVANCE_INVOICE:
        yield Finding(
            "With the VAT point date code (BT-8) 432 on an invoice that is not an advance "
            "invoice, VAT is due on collection (cash accounting), so the actual delivery date "
            "(BT-72) is required.",
            element,
        )


RULE = Rule(
    id="SRB-018",
    title="The actual delivery date is given when VAT is due on supply or on collection",
    terms=("BT-8", "BT-72"),
    references=(
        Reference("srb-cius", "1.3, Table 1, BT-8"),
        Reference("srb-cius", "1.3, Table 1, BT-72"),
    ),
    check=check,
)
