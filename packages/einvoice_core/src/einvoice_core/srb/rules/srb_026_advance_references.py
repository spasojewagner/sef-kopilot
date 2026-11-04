"""SRB-026: every advance used names one of the invoice's preceding invoices (BT-E1, BT-25).

SRB-CIUS has each advance used in the Serbian extension (BG-E1) give the number of its
advance invoice "as stated in BT-25": the advance invoice is also referenced as a preceding
invoice of this one (BG-3), so that the two references can be matched.
"""

from __future__ import annotations

from collections.abc import Iterator

from einvoice_core.srb.extension import ADVANCES
from einvoice_core.srb.rule import Document, Finding, Reference, Rule


def check(document: Document) -> Iterator[Finding]:
    preceding = {
        number
        for reference in document.find_all("cac:BillingReference/cac:InvoiceDocumentReference")
        if (number := document.text("cbc:ID", reference)) is not None
    }
    for advance in document.find_all(ADVANCES):
        number = document.text("cbc:ID", advance)
        if number is None:
            yield Finding(
                "An advance used on the invoice (BG-E1) must give the number of its advance "
                "invoice (BT-E1).",
                advance,
            )
        elif number not in preceding:
            yield Finding(
                f"The advance invoice {number!r} used on this invoice (BT-E1) must also be "
                "referenced as a preceding invoice (BG-3, BT-25), with the same number.",
                document.find("cbc:ID", advance),
            )


RULE = Rule(
    id="SRB-026",
    title="Every advance used names one of the invoice's preceding invoices",
    terms=("BG-E1", "BT-E1", "BG-3", "BT-25"),
    references=(Reference("srb-cius", "1.4, Table 2, BT-E1"),),
    check=check,
)
