"""SRB-027: on a foreign-currency invoice the extension's VAT breakdowns are also in RSD.

VAT is always accounted in dinars (SRB-CIUS 1.4). When the invoice currency is not RSD, the
advances used and the reduced totals of the Serbian extension therefore repeat their VAT
breakdown in RSD (BG-E5 for the advances, BG-E6 for the reduced totals), each in a VAT total
of its own.
"""

from __future__ import annotations

from collections.abc import Iterator

from einvoice_core.srb.extension import ADVANCES, DINAR, REDUCED_TOTALS, has_breakdown_in
from einvoice_core.srb.rule import Document, Finding, Reference, Rule

PARTS = (
    (ADVANCES, "advance used (BG-E1)", "BG-E5"),
    (REDUCED_TOTALS, "reduced totals (BG-E3)", "BG-E6"),
)


def check(document: Document) -> Iterator[Finding]:
    currency = document.text("cbc:DocumentCurrencyCode")
    if currency is None or currency == DINAR:
        return
    for path, part, group in PARTS:
        for element in document.find_all(path):
            if not has_breakdown_in(document, element, DINAR):
                yield Finding(
                    f"On an invoice in {currency}, the {part} must also give its VAT breakdown "
                    f"in RSD ({group}): a VAT total in RSD with a subtotal per VAT category.",
                    element,
                )


RULE = Rule(
    id="SRB-027",
    title="On a foreign-currency invoice the extension's VAT breakdowns are also in RSD",
    terms=("BG-E5", "BG-E6"),
    references=(
        Reference("srb-cius", "1.4, Table 2, BG-E5"),
        Reference("srb-cius", "1.4, Table 2, BG-E6"),
    ),
    check=check,
)
