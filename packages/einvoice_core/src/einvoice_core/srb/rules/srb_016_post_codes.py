"""SRB-016: a resident seller and a tax representative give a post code (BT-38, BT-67).

SRB-CIUS makes the seller's post code mandatory for residents (a seller whose address is in
Serbia, country code RS) and the tax representative's post code mandatory outright
(EN 16931: 0..1, struck out for 1..1). The buyer's post code is SRB-017.
"""

from __future__ import annotations

from collections.abc import Iterator

from lxml import etree

from einvoice_core.srb.paths import COUNTRY_CODE, POST_CODE, SELLER, SERBIA, TAX_REPRESENTATIVE
from einvoice_core.srb.rule import Document, Finding, Reference, Rule


def _missing(document: Document, party: etree._Element, name: str, term: str) -> Finding:
    address = document.find("cac:PostalAddress", party)
    return Finding(
        f"The {name}'s postal address must give the post code ({term}).",
        party if address is None else address,
    )


def check(document: Document) -> Iterator[Finding]:
    for seller in document.find_all(SELLER):
        resident = document.text(COUNTRY_CODE, seller) == SERBIA
        if resident and document.text(POST_CODE, seller) is None:
            yield _missing(document, seller, "seller", "BT-38")
    for representative in document.find_all(TAX_REPRESENTATIVE):
        if document.text(POST_CODE, representative) is None:
            yield _missing(document, representative, "tax representative", "BT-67")


RULE = Rule(
    id="SRB-016",
    title="A resident seller and a tax representative give a post code",
    terms=("BT-38", "BT-67"),
    references=(
        Reference("srb-cius", "1.3, Table 1, BT-38"),
        Reference("srb-cius", "1.3, Table 1, BT-67"),
    ),
    check=check,
)
