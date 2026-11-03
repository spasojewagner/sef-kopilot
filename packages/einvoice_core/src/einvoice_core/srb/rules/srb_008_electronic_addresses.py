"""SRB-008: seller and buyer are addressed by PIB with scheme 9948 (BT-34, BT-49).

SEF routes an invoice by these addresses, so SRB-CIUS makes both mandatory. This rule checks
presence, form and scheme; SRB-009 checks that a nine-digit PIB is one the rulebook can assign.
"""

from __future__ import annotations

from collections.abc import Iterator

from lxml import etree

from einvoice_core.srb.identifiers import has_pib_form
from einvoice_core.srb.paths import BUYER, SELLER
from einvoice_core.srb.rule import Document, Finding, Reference, Rule

SCHEME = "9948"
PARTIES = (
    (SELLER, "seller electronic address (BT-34)"),
    (BUYER, "buyer electronic address (BT-49)"),
)


def check(document: Document) -> Iterator[Finding]:
    for path, term in PARTIES:
        for party in document.find_all(path):
            yield from _check_party(document, party, term)


def _check_party(document: Document, party: etree._Element, term: str) -> Iterator[Finding]:
    element = document.find("cbc:EndpointID", party)
    if element is None:
        yield Finding(f"The {term} is required: the party's PIB with scheme 9948.", party)
        return
    value = (element.text or "").strip()
    if not has_pib_form(value):
        yield Finding(
            f"The {term} must be a PIB of nine digits, or of thirteen for a JMBG; found {value!r}.",
            element,
        )
    scheme = element.get("schemeID")
    if scheme != SCHEME:
        yield Finding(
            f"The scheme of the {term} must be 9948, not {scheme!r}.", element, "schemeID"
        )


RULE = Rule(
    id="SRB-008",
    title="Seller and buyer electronic addresses are a PIB with scheme 9948",
    terms=("BT-34", "BT-49"),
    references=(
        Reference("srb-cius", "1.3, Table 1, BT-34"),
        Reference("srb-cius", "1.3, Table 1, BT-49"),
    ),
    check=check,
)
