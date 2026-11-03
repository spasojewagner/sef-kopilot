"""SRB-007: the parties have a VAT identifier RS<PIB> (BT-31, BT-48, BT-63).

SRB-CIUS makes the three identifiers mandatory (the tax representative's whenever BG-11 is
present) and prescribes the value: the PIB with the prefix ``RS``, where the PIB may be a
JMBG as the PIB rulebook allows. This rule checks presence and form; SRB-009 checks that a
nine-digit PIB is one the rulebook can assign.
"""

from __future__ import annotations

from collections.abc import Iterator

from lxml import etree

from einvoice_core.srb.identifiers import has_pib_form
from einvoice_core.srb.paths import BUYER, SELLER, TAX_REPRESENTATIVE, VAT_IDENTIFIER
from einvoice_core.srb.rule import Document, Finding, Reference, Rule

PREFIX = "RS"
PARTIES = (
    (SELLER, "seller", "BT-31"),
    (BUYER, "buyer", "BT-48"),
    (TAX_REPRESENTATIVE, "tax representative", "BT-63"),
)


def check(document: Document) -> Iterator[Finding]:
    for path, party_name, term in PARTIES:
        for party in document.find_all(path):
            yield from _check_party(document, party, party_name, term)


def _check_party(
    document: Document, party: etree._Element, party_name: str, term: str
) -> Iterator[Finding]:
    identifiers = document.find_all(VAT_IDENTIFIER, party)
    if not identifiers:
        yield Finding(
            f"The {party_name} VAT identifier ({term}) is required: {PREFIX} followed by "
            f"the {party_name}'s PIB, registered under the tax scheme VAT.",
            party,
        )
    for element in identifiers:
        value = (element.text or "").strip()
        if not (value.startswith(PREFIX) and has_pib_form(value.removeprefix(PREFIX))):
            yield Finding(
                f"The {party_name} VAT identifier ({term}) must be {PREFIX} followed by a "
                f"PIB of nine digits, or of thirteen for a JMBG; found {value!r}.",
                element,
            )


RULE = Rule(
    id="SRB-007",
    title="Seller, buyer and tax representative have a VAT identifier RS followed by a PIB",
    terms=("BT-31", "BT-48", "BT-63"),
    references=(
        Reference("srb-cius", "1.3, Table 1, BT-31"),
        Reference("srb-cius", "1.3, Table 1, BT-48"),
        Reference("srb-cius", "1.3, Table 1, BT-63"),
        Reference("pib-rulebook", "Article 2"),
    ),
    check=check,
)
