"""SRB-013: the seller states its VAT registration status (BT-32).

SRB-CIUS makes BT-32 mandatory (EN 16931: 0..1, struck out for 1..1) and gives it a Serbian
meaning: whether the seller is in the VAT register, written as a party tax scheme
``RS-VAT-STATUS`` whose value is ``VAT`` or ``NO-VAT`` (SRB-014 checks the value).

Severity: warning. None of the 17 example documents published with the specification has
BT-32, so whether SEF already rejects an invoice without it is to be confirmed in the SEF
demo environment (M5); until then the rule reports, but does not block (ADR-0006).
"""

from __future__ import annotations

from collections.abc import Iterator

from einvoice_core.srb.paths import SELLER, VAT_STATUS
from einvoice_core.srb.rule import Document, Finding, Reference, Rule
from einvoice_core.violations import Severity


def check(document: Document) -> Iterator[Finding]:
    for seller in document.find_all(SELLER):
        if not document.find_all(VAT_STATUS, seller):
            yield Finding(
                "The seller's VAT registration status (BT-32) is missing: SRB-CIUS requires a "
                "party tax scheme RS-VAT-STATUS with the value VAT (in the VAT register) or "
                "NO-VAT (not in it).",
                seller,
            )


RULE = Rule(
    id="SRB-013",
    title="The seller states its VAT registration status",
    terms=("BT-32",),
    references=(Reference("srb-cius", "1.3, Table 1, BT-32"),),
    check=check,
    severity=Severity.WARNING,
)
