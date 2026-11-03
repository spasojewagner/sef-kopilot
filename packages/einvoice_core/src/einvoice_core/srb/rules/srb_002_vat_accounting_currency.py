"""SRB-002: VAT is accounted in dinars (BT-6)."""

from __future__ import annotations

from collections.abc import Iterator

from einvoice_core.srb.rule import Document, Finding, Reference, Rule

DINAR = "RSD"


def check(document: Document) -> Iterator[Finding]:
    invoice = document.invoice
    element = document.find("cbc:TaxCurrencyCode")
    if invoice.tax_currency is not None and invoice.tax_currency != DINAR:
        yield Finding(
            f"The VAT accounting currency (BT-6) must be RSD, not {invoice.tax_currency!r}.",
            element,
        )
    elif invoice.currency not in (None, DINAR) and invoice.tax_currency is None:
        yield Finding(
            f"An invoice in {invoice.currency} must state RSD as the VAT accounting currency "
            "(BT-6) and give the VAT total in RSD.",
            document.root,
        )


RULE = Rule(
    id="SRB-002",
    title="The VAT accounting currency is RSD",
    terms=("BT-5", "BT-6"),
    references=(Reference("srb-cius", "1.4"),),
    check=check,
)
