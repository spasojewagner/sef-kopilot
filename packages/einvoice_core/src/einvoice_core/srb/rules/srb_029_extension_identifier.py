"""SRB-029: an invoice that uses the Serbian extension says so in BT-24.

SRB-CIUS 1.2 gives two specification identifiers: the short one when the extension is not
applied, and the one ending ``#conformant#urn:mfin.gov.rs:srbdtext:2022`` when it is (which
may also be used without extension elements). An invoice with ``SrbDtExt`` content under the
short identifier therefore misstates its specification.

Severity: warning. The Ministry's own examples of final invoices carry the extension under
the short identifier, so whether SEF distinguishes the two is to be confirmed in the SEF demo
environment (M5); until then the rule reports, but does not block (ADR-0006).
"""

from __future__ import annotations

from collections.abc import Iterator

from einvoice_core.srb.codes import SPECIFICATION_IDENTIFIER, SPECIFICATION_IDENTIFIER_EXTENDED
from einvoice_core.srb.extension import EXTENSION
from einvoice_core.srb.rule import Document, Finding, Reference, Rule
from einvoice_core.violations import Severity


def check(document: Document) -> Iterator[Finding]:
    extension = document.find(EXTENSION)
    element = document.find("cbc:CustomizationID")
    if extension is None or len(extension) == 0 or element is None:
        return
    if document.text("cbc:CustomizationID") == SPECIFICATION_IDENTIFIER:
        yield Finding(
            "The invoice uses the Serbian extension (SrbDtExt), so its specification identifier "
            f"(BT-24) is {SPECIFICATION_IDENTIFIER_EXTENDED!r}, not the identifier without the "
            "extension.",
            element,
        )


RULE = Rule(
    id="SRB-029",
    title="An invoice that uses the Serbian extension says so in BT-24",
    terms=("BT-24",),
    references=(Reference("srb-cius", "1.2"),),
    check=check,
    severity=Severity.WARNING,
)
