"""SRB-004: an advance invoice states when the advance is paid (BT-9)."""

from __future__ import annotations

from collections.abc import Iterator

from einvoice_core.srb.rule import Document, Finding, Reference, Rule

ADVANCE_INVOICE = "386"


def check(document: Document) -> Iterator[Finding]:
    invoice = document.invoice
    if invoice.type_code == ADVANCE_INVOICE and invoice.due_date is None:
        yield Finding(
            "An advance invoice (BT-3 = 386) must give the payment due date (BT-9), which is "
            "the date of the advance payment.",
            document.root,
        )


RULE = Rule(
    id="SRB-004",
    title="An advance invoice has a payment due date",
    terms=("BT-3", "BT-9"),
    references=(Reference("srb-cius", "1.3, Table 1, BT-9"),),
    check=check,
)
