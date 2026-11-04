"""SRB-010: a public-procurement buyer reference is JN-JBKJS: and five digits (BT-10).

When an invoice is issued under a public procurement contract that the buyer did not award
itself, SRB-CIUS has BT-10 begin with ``JN-JBKJS:``, followed by the five digits of the JBKJS
of the contracting authority that did, then optionally a hyphen and further characters.
Whether an invoice is such a case cannot be seen from the invoice, so the rule checks the form
whenever a buyer reference starts with the prefix, in any letter case.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from einvoice_core.srb.rule import Document, Finding, Reference, Rule

PREFIX = "JN-JBKJS:"
FORM = re.compile(r"JN-JBKJS:[0-9]{5}(-.*)?", re.DOTALL)


def check(document: Document) -> Iterator[Finding]:
    element = document.find("cbc:BuyerReference")
    value = document.text("cbc:BuyerReference")
    # A reference that starts like the prefix, in any letter case or without the colon, is
    # meant as one and must have its exact form.
    if element is None or value is None or not value.upper().startswith(PREFIX.rstrip(":")):
        return
    if FORM.fullmatch(value) is None:
        yield Finding(
            "A public-procurement buyer reference (BT-10) must be JN-JBKJS: followed by the "
            "five-digit JBKJS of the contracting authority, optionally followed by a hyphen "
            f"and further characters; found {value!r}.",
            element,
        )


RULE = Rule(
    id="SRB-010",
    title="A public-procurement buyer reference is JN-JBKJS: followed by five digits",
    terms=("BT-10",),
    references=(Reference("srb-cius", "1.3, Table 1, BT-10"),),
    check=check,
)
