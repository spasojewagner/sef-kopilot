"""SRB-003: the VAT point date is given as a code, never as a date (BT-7, BT-8)."""

from __future__ import annotations

from collections.abc import Iterator

from einvoice_core.srb.rule import Document, Finding, Reference, Rule


def check(document: Document) -> Iterator[Finding]:
    element = document.find("cbc:TaxPointDate")
    if element is not None:
        yield Finding(
            "The VAT point date (BT-7) is not used in Serbia; give the VAT point date code "
            "(BT-8) instead.",
            element,
        )


RULE = Rule(
    id="SRB-003",
    title="The VAT point date (BT-7) is not used",
    terms=("BT-7", "BT-8"),
    references=(Reference("srb-cius", "1.3, Table 1, BT-7"),),
    check=check,
)
