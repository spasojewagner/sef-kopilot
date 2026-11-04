"""SRB-024: exempt and non-taxed VAT breakdowns give an exemption reason code (BT-121).

For the categories Z, E, R, O, OE, SS and N the Ministry's list says to state one of the codes
it offers; the code is BT-121 of the VAT breakdown. (For AE the list offers codes without
saying so; EN 16931 already requires a reason, code or text, for reverse charge.)
"""

from __future__ import annotations

from collections.abc import Iterator

from einvoice_core.srb.rule import Document, Finding, Reference, Rule
from einvoice_core.srb.vat import CATEGORIES, CODE_REQUIRED, breakdown_categories


def check(document: Document) -> Iterator[Finding]:
    for category in breakdown_categories(document):
        code = document.text("cbc:ID", category.element)
        if code in CODE_REQUIRED and (
            document.text("cbc:TaxExemptionReasonCode", category.element) is None
        ):
            yield Finding(
                f"A VAT breakdown in category {code} ({CATEGORIES[code]}) must give the VAT "
                "exemption reason code (BT-121), one of the codes the Ministry lists for it.",
                category.element,
            )


RULE = Rule(
    id="SRB-024",
    title="Exempt and non-taxed VAT breakdowns give an exemption reason code",
    terms=("BT-118", "BT-121"),
    references=(
        Reference("tax-categories", "the list for each tax category"),
        Reference("srb-cius", "1.3, Table 1, BT-121"),
    ),
    check=check,
)
