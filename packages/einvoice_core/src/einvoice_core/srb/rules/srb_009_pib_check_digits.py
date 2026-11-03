"""SRB-009: every nine-digit PIB is one the PIB rulebook can assign (BT-31, BT-34, BT-48, ...).

The rulebook builds a PIB from an eight-digit serial number between 10000001 and 99999999 and
an ISO 7064 MOD 11,10 check digit, so a PIB outside that range or with another last digit
cannot exist; usually a digit was mistyped. SRB-007 and SRB-008 check where PIBs must appear
and their form; this rule checks the numbers themselves, wherever SRB-CIUS puts a PIB.
Thirteen-digit PIBs (a JMBG) are left alone: their check digit is not defined by the rulebook.
"""

from __future__ import annotations

from collections.abc import Iterator

from einvoice_core.srb.identifiers import (
    PIB_DIGITS,
    PIB_SERIALS,
    has_pib_form,
    pib_check_digit,
)
from einvoice_core.srb.paths import BUYER, SELLER, TAX_REPRESENTATIVE, VAT_IDENTIFIER
from einvoice_core.srb.rule import Document, Finding, Reference, Rule

#: Where a PIB appears: the party, the element within it, the prefix before the PIB, the term.
PIBS = (
    (SELLER, VAT_IDENTIFIER, "RS", "seller VAT identifier (BT-31)"),
    (SELLER, "cbc:EndpointID", "", "seller electronic address (BT-34)"),
    (BUYER, VAT_IDENTIFIER, "RS", "buyer VAT identifier (BT-48)"),
    (BUYER, "cbc:EndpointID", "", "buyer electronic address (BT-49)"),
    (TAX_REPRESENTATIVE, VAT_IDENTIFIER, "RS", "tax representative VAT identifier (BT-63)"),
)


def check(document: Document) -> Iterator[Finding]:
    for party, path, prefix, term in PIBS:
        for element in document.find_all(f"{party}/{path}"):
            value = (element.text or "").strip()
            pib = value.removeprefix(prefix)
            if not value.startswith(prefix) or len(pib) != PIB_DIGITS or not has_pib_form(pib):
                continue  # not a nine-digit PIB at all: SRB-007 and SRB-008 report the form
            serial, last = pib[:8], int(pib[8])
            if int(serial) not in PIB_SERIALS:
                yield Finding(
                    f"The PIB {pib} in the {term} cannot exist: the first eight digits of a "
                    f"PIB run from {PIB_SERIALS.start} to {PIB_SERIALS.stop - 1}.",
                    element,
                )
            elif last != (expected := pib_check_digit(serial)):
                yield Finding(
                    f"The PIB {pib} in the {term} cannot exist: its last digit must be the "
                    f"check digit of {serial}, which is {expected}, not {last}.",
                    element,
                )


RULE = Rule(
    id="SRB-009",
    title="Every nine-digit PIB has a serial number in range and a valid check digit",
    terms=("BT-31", "BT-34", "BT-48", "BT-49", "BT-63"),
    references=(
        Reference("pib-rulebook", "Article 2"),
        Reference("srb-cius", "1.3, Table 1, BT-31"),
        Reference("srb-cius", "1.3, Table 1, BT-34"),
    ),
    check=check,
)
