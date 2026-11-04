"""SRB-021: categories S and AE are charged at 20 % or 10 % (BT-96, BT-103, BT-119, BT-152).

SRB-CIUS defines the standard-rated categories as S20 and S10 and the reverse-charge ones as
AE20 and AE10: code and rate together. A VAT category S or AE therefore states the rate 20 or
10. (EN 16931 gives reverse charge the rate 0; SEF's AE carries the rate the recipient owes.)
"""

from __future__ import annotations

from collections.abc import Iterator

from einvoice_core.srb.rule import Document, Finding, Reference, Rule
from einvoice_core.srb.vat import RATED, RATES, rate, tax_categories


def check(document: Document) -> Iterator[Finding]:
    for category in tax_categories(document):
        code = document.text("cbc:ID", category.element)
        if code not in RATED:
            continue
        percent = rate(document, category.element)
        if percent not in RATES:
            found = "no rate" if percent is None else f"{percent}"
            element = document.find("cbc:Percent", category.element)
            yield Finding(
                f"The {category.where} VAT category {code} is charged at 20 or 10 percent, "
                f"stated in the rate ({category.rate_term}); found {found}.",
                category.element if element is None else element,
            )


RULE = Rule(
    id="SRB-021",
    title="Categories S and AE are charged at 20 or 10 percent",
    terms=("BT-96", "BT-103", "BT-119", "BT-152"),
    references=(Reference("srb-cius", "1.3, Table 1, BT-118"),),
    check=check,
)
