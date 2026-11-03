"""SRB-001: the invoice type code is one of the four SEF accepts (BT-3)."""

from __future__ import annotations

from collections.abc import Iterator

from einvoice_core.srb.codes import INVOICE_TYPE_CODES
from einvoice_core.srb.rule import Document, Finding, Reference, Rule


def check(document: Document) -> Iterator[Finding]:
    element = document.find("cbc:InvoiceTypeCode | cbc:CreditNoteTypeCode")
    code = document.invoice.type_code
    if element is not None and code not in INVOICE_TYPE_CODES:
        allowed = ", ".join(INVOICE_TYPE_CODES)
        yield Finding(
            f"The invoice type code (BT-3) must be one of {allowed}, not {code!r}.", element
        )


RULE = Rule(
    id="SRB-001",
    title="The invoice type code is 380, 381, 383 or 386",
    terms=("BT-3",),
    references=(Reference("srb-cius", "1.3, Table 1, BT-3"),),
    check=check,
)
