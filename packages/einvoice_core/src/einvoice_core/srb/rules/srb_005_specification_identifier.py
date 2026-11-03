"""SRB-005: the specification identifier is the SRB-CIUS identifier (BT-24)."""

from __future__ import annotations

from collections.abc import Iterator

from einvoice_core.srb.codes import SPECIFICATION_IDENTIFIERS
from einvoice_core.srb.rule import Document, Finding, Reference, Rule


def check(document: Document) -> Iterator[Finding]:
    element = document.find("cbc:CustomizationID")
    value = document.invoice.specification_id
    if element is not None and value not in SPECIFICATION_IDENTIFIERS:
        yield Finding(
            f"The specification identifier (BT-24) must be {SPECIFICATION_IDENTIFIERS[0]!r}, or "
            f"{SPECIFICATION_IDENTIFIERS[1]!r} with the Serbian extension; found {value!r}.",
            element,
        )


RULE = Rule(
    id="SRB-005",
    title="The specification identifier is the SRB-CIUS identifier",
    terms=("BT-24",),
    references=(Reference("srb-cius", "1.2"), Reference("srb-cius", "1.3, Table 1, BT-24")),
    check=check,
)
