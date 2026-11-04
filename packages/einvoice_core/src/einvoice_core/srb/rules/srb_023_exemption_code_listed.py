"""SRB-023: a VAT exemption reason code is in the Ministry's list (BT-121).

SRB-CIUS has BT-121 take its codes from the provisions of the VAT law, which the Ministry lists
per category ("Poreske kategorije i šifre od 1. septembra 2024."). A code that is in none of the
lists is probably mistyped or invented.

Severity: warning. The list is dated and SEF maintains its own copy, which may already contain
codes added after 1 September 2024; whether SEF rejects an unlisted code is to be confirmed in
the SEF demo environment (M5). A listed code under the wrong category is fatal (SRB-022).
"""

from __future__ import annotations

from collections.abc import Iterator

from einvoice_core.srb.rule import Document, Finding, Reference, Rule
from einvoice_core.srb.vat import EXEMPTION_CODES, breakdown_categories
from einvoice_core.violations import Severity

LISTED = frozenset(code for codes in EXEMPTION_CODES.values() for code in codes)


def check(document: Document) -> Iterator[Finding]:
    for category in breakdown_categories(document):
        element = document.find("cbc:TaxExemptionReasonCode", category.element)
        code = document.text("cbc:TaxExemptionReasonCode", category.element)
        if element is not None and code is not None and code not in LISTED:
            yield Finding(
                f"The VAT exemption reason code {code!r} (BT-121) is not in the Ministry's list "
                "of tax categories and codes of 1 September 2024.",
                element,
            )


RULE = Rule(
    id="SRB-023",
    title="A VAT exemption reason code is in the Ministry's list",
    terms=("BT-121",),
    references=(
        Reference("tax-categories", "the list for each tax category"),
        Reference("srb-cius", "1.3, Table 1, BT-121"),
    ),
    check=check,
    severity=Severity.WARNING,
)
