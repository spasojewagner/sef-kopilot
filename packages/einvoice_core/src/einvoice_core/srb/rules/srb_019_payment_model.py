"""SRB-019: a payment model in the remittance information is written (modNN) reference (BT-83).

For domestic payments BT-83 carries the payment reference (poziv na broj). When a payment
model is given, SRB-CIUS prescribes its notation: ``(mod`` and the model number without a
space, a closing parenthesis, exactly one space, then the reference — ``(mod97) 1234567890``.
Payment models are two-digit numbers. The rule applies to every remittance information that
starts by naming a model (``mod`` and a digit, in any letter case, with or without the
parenthesis); a reference without a model is not affected.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from einvoice_core.srb.rule import Document, Finding, Reference, Rule

NAMES_A_MODEL = re.compile(r"\(?\s*mod\s*[0-9]", re.IGNORECASE)
NOTATION = re.compile(r"\(mod[0-9]{2}\) \S.*", re.DOTALL)


def check(document: Document) -> Iterator[Finding]:
    for element in document.find_all("cac:PaymentMeans/cbc:PaymentID"):
        value = (element.text or "").strip()
        if NAMES_A_MODEL.match(value) and NOTATION.fullmatch(value) is None:
            yield Finding(
                "A payment model in the remittance information (BT-83) is written as (mod, "
                "the two-digit model, a closing parenthesis, one space and the reference, "
                f"e.g. '(mod97) 1234567890'; found {value!r}.",
                element,
            )


RULE = Rule(
    id="SRB-019",
    title="A payment model in the remittance information is written (modNN) reference",
    terms=("BT-83",),
    references=(Reference("srb-cius", "1.3, Table 1, BT-83"),),
    check=check,
)
