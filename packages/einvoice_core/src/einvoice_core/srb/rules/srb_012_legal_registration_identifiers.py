"""SRB-012: legal registration identifiers are stated without a scheme (BT-30, BT-47, BT-61).

SRB-CIUS requires the registration number (matični broj; for a natural person without a
separately registered business, the JMBG) of the buyer (BT-47, made 1..1) and of the payee
when there is one (BT-61, made 1..1), and of the seller when the seller is resident (BT-30).
No scheme identifier is given for the buyer, nor for a resident seller. A seller counts as
resident when its address is in Serbia (country code RS). The payee has no address in
EN 16931, so the scheme note "for residents" cannot be checked for it.
"""

from __future__ import annotations

from collections.abc import Iterator

from lxml import etree

from einvoice_core.srb.paths import (
    BUYER,
    COUNTRY_CODE,
    LEGAL_REGISTRATION,
    PAYEE,
    SELLER,
    SERBIA,
)
from einvoice_core.srb.rule import Document, Finding, Reference, Rule


def _missing(document: Document, party: etree._Element, name: str, term: str) -> Finding:
    entity = document.find("cac:PartyLegalEntity", party)
    return Finding(
        f"The {name} legal registration identifier ({term}) is required: the registration "
        "number, or the JMBG of a natural person without a separately registered business.",
        party if entity is None else entity,
    )


def _without_scheme(document: Document, party: etree._Element, term: str) -> Iterator[Finding]:
    element = document.find(LEGAL_REGISTRATION, party)
    if element is not None and "schemeID" in element.attrib:
        yield Finding(
            f"The legal registration identifier ({term}) has no scheme identifier; found "
            f"{element.get('schemeID')!r}.",
            element,
            "schemeID",
        )


def check(document: Document) -> Iterator[Finding]:
    for seller in document.find_all(SELLER):
        if document.text(COUNTRY_CODE, seller) == SERBIA:
            if document.text(LEGAL_REGISTRATION, seller) is None:
                yield _missing(document, seller, "seller", "BT-30")
            yield from _without_scheme(document, seller, "BT-30")
    for buyer in document.find_all(BUYER):
        if document.text(LEGAL_REGISTRATION, buyer) is None:
            yield _missing(document, buyer, "buyer", "BT-47")
        yield from _without_scheme(document, buyer, "BT-47")
    for payee in document.find_all(PAYEE):
        if document.text(LEGAL_REGISTRATION, payee) is None:
            yield _missing(document, payee, "payee", "BT-61")


RULE = Rule(
    id="SRB-012",
    title="Buyer, payee and a resident seller give a legal registration number, without a scheme",
    terms=("BT-30", "BT-47", "BT-61"),
    references=(
        Reference("srb-cius", "1.3, Table 1, BT-30"),
        Reference("srb-cius", "1.3, Table 1, BT-47"),
        Reference("srb-cius", "1.3, Table 1, BT-61"),
    ),
    check=check,
)
