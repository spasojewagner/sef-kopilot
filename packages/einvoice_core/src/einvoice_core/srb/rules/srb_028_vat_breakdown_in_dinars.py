"""SRB-028: a foreign-currency invoice gives its VAT breakdown in RSD as well (BG-E7).

VAT is always accounted in dinars (SRB-CIUS 1.4). An invoice whose currency is not RSD keeps
its VAT breakdown (BG-23) in the invoice currency and adds, in a second VAT total in RSD, the
breakdown in dinars (BG-E7, used when the invoice currency is not RSD). EN 16931 asks only
for the VAT total in the accounting currency (BT-111); SRB-CIUS wants the subtotals too.
"""

from __future__ import annotations

from collections.abc import Iterator

from einvoice_core.srb.extension import DINAR, has_breakdown_in
from einvoice_core.srb.rule import Document, Finding, Reference, Rule


def check(document: Document) -> Iterator[Finding]:
    currency = document.text("cbc:DocumentCurrencyCode")
    if currency is None or currency == DINAR or has_breakdown_in(document, document.root, DINAR):
        return
    in_dinars = [
        total
        for total in document.find_all("cac:TaxTotal")
        if (amount := document.find("cbc:TaxAmount", total)) is not None
        and amount.get("currencyID") == DINAR
    ]
    yield Finding(
        f"An invoice in {currency} must also give its VAT breakdown in RSD (BG-E7): a VAT total "
        "in RSD with a subtotal per VAT category, beside the breakdown in the invoice currency.",
        in_dinars[0] if in_dinars else document.root,
    )


RULE = Rule(
    id="SRB-028",
    title="A foreign-currency invoice gives its VAT breakdown in RSD as well",
    terms=("BG-E7", "BT-5"),
    references=(
        Reference("srb-cius", "1.4"),
        Reference("srb-cius", "1.4, Table 2, BG-E7"),
    ),
    check=check,
)
