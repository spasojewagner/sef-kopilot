"""SRB-020: every VAT category code is one SRB-CIUS allows (BT-95, BT-102, BT-118, BT-151).

SRB-CIUS allows S, Z, E, AE, R, O, OE, SS and N, for the VAT breakdown and, by reference to
the same note, for document level allowances and charges and for invoice lines. The specification
writes the reverse-charge categories as AE10 and AE20, but as category code and rate together:
the code is AE and the rate goes into the rate element, as for S10 and S20. The Ministry's
documents spell AE in Cyrillic letters; the code is Latin.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from einvoice_core.srb.rule import Document, Finding, Reference, Rule
from einvoice_core.srb.vat import CATEGORIES, RATED, tax_categories

#: Cyrillic letters that look like the Latin letters of the codes: A, IE and O.
LOOK_ALIKES = str.maketrans({"\u0410": "A", "\u0415": "E", "\u041e": "O"})
WITH_RATE = re.compile(r"(?P<code>S|AE)(?P<rate>10|20)")


def _hint(value: str) -> str:
    latin = value.translate(LOOK_ALIKES)
    if latin != value and latin in CATEGORIES:
        return f" It is written with Cyrillic letters; the code is the Latin {latin!r}."
    match = WITH_RATE.fullmatch(latin)
    if match and match["code"] in RATED:
        return (
            f" The category {value} is the code {match['code']!r} with the rate "
            f"{match['rate']} in the rate element."
        )
    return ""


def check(document: Document) -> Iterator[Finding]:
    allowed = ", ".join(CATEGORIES)
    for category in tax_categories(document):
        element = document.find("cbc:ID", category.element)
        value = document.text("cbc:ID", category.element)
        if element is not None and value is not None and value not in CATEGORIES:
            yield Finding(
                f"The {category.where} VAT category code ({category.code_term}) must be one of "
                f"{allowed}; found {value!r}.{_hint(value)}",
                element,
            )


RULE = Rule(
    id="SRB-020",
    title="Every VAT category code is one SRB-CIUS allows",
    terms=("BT-95", "BT-102", "BT-118", "BT-151"),
    references=(
        Reference("srb-cius", "1.3, Table 1, BT-118"),
        Reference("srb-cius", "1.3, Table 1, BT-95, BT-102, BT-151"),
    ),
    check=check,
)
