"""SRB-006: a public-funds user is identified by its JBKJS (BT-29, BT-46, BT-60)."""

from __future__ import annotations

from collections.abc import Iterator

from lxml import etree

from einvoice_core.srb.identifiers import is_jbkjs
from einvoice_core.srb.paths import BUYER, PAYEE, SELLER
from einvoice_core.srb.rule import Document, Finding, Reference, Rule

PREFIX = "JBKJS:"
PARTIES = (
    (SELLER, "seller identifier (BT-29)"),
    (BUYER, "buyer identifier (BT-46)"),
    (PAYEE, "payee identifier (BT-60)"),
)


def check(document: Document) -> Iterator[Finding]:
    for path, term in PARTIES:
        for party in document.find_all(path):
            yield from _check_party(document, party, term)


def _check_party(document: Document, party: etree._Element, term: str) -> Iterator[Finding]:
    identifiers = [
        element
        for element in document.find_all("cac:PartyIdentification/cbc:ID", party)
        if (element.text or "").strip().startswith(PREFIX)
    ]
    for element in identifiers:
        value = (element.text or "").strip()
        if not is_jbkjs(value.removeprefix(PREFIX)):
            yield Finding(f"The {term} {value!r} must be JBKJS: followed by five digits.", element)
        if "schemeID" in element.attrib:
            yield Finding(f"The JBKJS {term} has no scheme identifier.", element, "schemeID")
    for element in identifiers[1:]:
        yield Finding(f"A party has one JBKJS {term}; this one is extra.", element)


RULE = Rule(
    id="SRB-006",
    title="A public-funds user has one JBKJS identifier of five digits, without a scheme",
    terms=("BT-29", "BT-46", "BT-60"),
    references=(
        Reference("srb-cius", "1.3, Table 1, BT-29"),
        Reference("srb-cius", "1.3, Table 1, BT-46"),
        Reference("srb-cius", "1.3, Table 1, BT-60"),
    ),
    check=check,
)
