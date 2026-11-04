"""SRB-014: the seller's VAT registration status is VAT or NO-VAT (BT-32)."""

from __future__ import annotations

from collections.abc import Iterator

from einvoice_core.srb.codes import VAT_STATUSES
from einvoice_core.srb.paths import SELLER, VAT_STATUS
from einvoice_core.srb.rule import Document, Finding, Reference, Rule


def check(document: Document) -> Iterator[Finding]:
    for element in document.find_all(f"{SELLER}/{VAT_STATUS}"):
        value = (element.text or "").strip()
        if value not in VAT_STATUSES:
            yield Finding(
                "The seller's VAT registration status (BT-32) must be VAT (in the VAT register) "
                f"or NO-VAT (not in it); found {value!r}.",
                element,
            )


RULE = Rule(
    id="SRB-014",
    title="The seller's VAT registration status is VAT or NO-VAT",
    terms=("BT-32",),
    references=(Reference("srb-cius", "1.3, Table 1, BT-32"),),
    check=check,
)
