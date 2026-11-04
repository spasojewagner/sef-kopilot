"""SRB-015: seller, buyer and tax representative addresses name the city (BT-37, BT-52, BT-66).

SRB-CIUS makes the three cities mandatory (EN 16931: 0..1, struck out for 1..1); the seller's
city also counts as the place where the invoice is issued.
"""

from __future__ import annotations

from collections.abc import Iterator

from einvoice_core.srb.paths import BUYER, CITY, SELLER, TAX_REPRESENTATIVE
from einvoice_core.srb.rule import Document, Finding, Reference, Rule

PARTIES = (
    (SELLER, "seller", "BT-37"),
    (BUYER, "buyer", "BT-52"),
    (TAX_REPRESENTATIVE, "tax representative", "BT-66"),
)


def check(document: Document) -> Iterator[Finding]:
    for path, name, term in PARTIES:
        for party in document.find_all(path):
            if document.text(CITY, party) is None:
                address = document.find("cac:PostalAddress", party)
                yield Finding(
                    f"The {name}'s postal address must name the city ({term}).",
                    party if address is None else address,
                )


RULE = Rule(
    id="SRB-015",
    title="Seller, buyer and tax representative addresses name the city",
    terms=("BT-37", "BT-52", "BT-66"),
    references=(
        Reference("srb-cius", "1.3, Table 1, BT-37"),
        Reference("srb-cius", "1.3, Table 1, BT-52"),
        Reference("srb-cius", "1.3, Table 1, BT-66"),
    ),
    check=check,
)
