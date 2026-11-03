"""SRB-011: a reference to a preceding invoice gives its issue date (BT-26).

EN 16931 makes BT-26 optional; SRB-CIUS makes it mandatory in every preceding invoice
reference (BG-3), so that the preceding invoice is identified by number and date.
"""

from __future__ import annotations

from collections.abc import Iterator

from einvoice_core.srb.rule import Document, Finding, Reference, Rule


def check(document: Document) -> Iterator[Finding]:
    for reference in document.find_all("cac:BillingReference/cac:InvoiceDocumentReference"):
        if document.text("cbc:IssueDate", reference) is None:
            number = document.text("cbc:ID", reference)
            yield Finding(
                f"The reference to the preceding invoice {number!r} (BG-3) must give that "
                "invoice's issue date (BT-26).",
                reference,
            )


RULE = Rule(
    id="SRB-011",
    title="A preceding invoice reference gives the preceding invoice's issue date",
    terms=("BG-3", "BT-26"),
    references=(Reference("srb-cius", "1.3, Table 1, BT-26"),),
    check=check,
)
