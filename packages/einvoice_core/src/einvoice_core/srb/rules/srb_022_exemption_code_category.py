"""SRB-022: a VAT exemption reason code is one of its own category's codes (BT-121).

The Ministry's list gives each VAT category its own codes (S20, S10, AE20 and AE10 by rate). A
code from the list of another category states a reason that does not fit the category: an
exemption with the right to deduct (Z) under a code for supplies not subject to VAT (O), say.
Codes the list does not contain at all are SRB-023's business.
"""

from __future__ import annotations

from collections.abc import Iterator

from einvoice_core.srb.rule import Document, Finding, Reference, Rule
from einvoice_core.srb.vat import EXEMPTION_CODES, breakdown_categories, list_key, rate


def _lists_with(code: str) -> list[str]:
    return [key for key, codes in EXEMPTION_CODES.items() if code in codes]


def check(document: Document) -> Iterator[Finding]:
    for category in breakdown_categories(document):
        element = document.find("cbc:TaxExemptionReasonCode", category.element)
        code = document.text("cbc:TaxExemptionReasonCode", category.element)
        key = list_key(
            document.text("cbc:ID", category.element) or "", rate(document, category.element)
        )
        if element is None or code is None or key is None:
            continue
        lists = _lists_with(code)
        if lists and key not in lists:
            yield Finding(
                f"The VAT exemption reason code {code!r} (BT-121) belongs to category "
                f"{' or '.join(lists)} in the Ministry's list, not to {key}.",
                element,
            )


RULE = Rule(
    id="SRB-022",
    title="A VAT exemption reason code is one of its own category's codes",
    terms=("BT-118", "BT-121"),
    references=(
        Reference("tax-categories", "the list for each tax category"),
        Reference("srb-cius", "1.3, Table 1, BT-121"),
    ),
    check=check,
)
