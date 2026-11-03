"""SRB-017: the buyer's address gives a post code (BT-53).

SRB-CIUS makes BT-53 mandatory (EN 16931: 0..1, struck out for 1..1).

Severity: warning. Nine of the 17 example documents published with the specification omit
the buyer's post code, so whether SEF rejects an invoice without it is to be confirmed in the
SEF demo environment (M5); until then the rule reports, but does not block (ADR-0006).
"""

from __future__ import annotations

from collections.abc import Iterator

from einvoice_core.srb.paths import BUYER, POST_CODE
from einvoice_core.srb.rule import Document, Finding, Reference, Rule
from einvoice_core.violations import Severity


def check(document: Document) -> Iterator[Finding]:
    for buyer in document.find_all(BUYER):
        if document.text(POST_CODE, buyer) is None:
            address = document.find("cac:PostalAddress", buyer)
            yield Finding(
                "The buyer's postal address must give the post code (BT-53).",
                buyer if address is None else address,
            )


RULE = Rule(
    id="SRB-017",
    title="The buyer's address gives a post code",
    terms=("BT-53",),
    references=(Reference("srb-cius", "1.3, Table 1, BT-53"),),
    check=check,
    severity=Severity.WARNING,
)
