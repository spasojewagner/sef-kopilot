"""The values a language model's answer names, and those its question does not contain
(ADR-0022).

A value is a date (ISO 8601, or as Serbian writes it, ``5. 10. 2026``), a number with decimals
or groups (an amount), a number with a percent sign (a rate), or a run of five digits or more
(a PIB, a registration number, an account). An answer may name a value only if the question the
model was sent contains it. Both are written one way before they are compared, a date as ISO
8601 and a number as its digits, so that ``1.200,00`` matches ``1200.00``. Shorter plain
numbers are not values: a check digit, the 7064 of ISO 7064, the 31 of BT-31.
"""

from __future__ import annotations

import re
from typing import Final

__all__ = ["invented", "plain", "values"]

#: The model writes identifiers with non-breaking hyphens (``BT\u201131``) and numbers with
#: non-breaking spaces; plain ones match what the specification writes and what a search for
#: ``BT-31`` finds.
_PLAIN: Final = str.maketrans({"\u2010": "-", "\u2011": "-", "\u00a0": " ", "\u202f": " "})

#: A number of this many digits or more is an identifier rather than a quantity.
_IDENTIFIER_DIGITS: Final = 5
#: A date, written as ISO 8601 or as Serbian writes it (5. 10. 2026).
_DATE: Final = re.compile(
    r"(?<!\d)(?:(\d{4})-(\d{1,2})-(\d{1,2})|(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4}))(?!\d)"
)
#: A number, with its decimals or groups and a percent sign, if any.
_NUMBER: Final = re.compile(r"\d+(?:[.,]\d+)*(?:\s?%)?")


def plain(text: str) -> str:
    """``text`` with the model's non-breaking hyphens and spaces written as plain ones."""
    return text.translate(_PLAIN)


def values(text: str, *, every: bool) -> dict[str, str]:
    """The dates and numbers ``text`` names, each written one way whatever way ``text`` wrote it
    (a date as ISO 8601, a number as its digits), with how ``text`` wrote it. Without ``every``,
    only the numbers that are values: with decimals or groups (an amount), with a percent sign (a
    rate), or of five digits or more (a PIB, a registration number, an account)."""
    found: dict[str, str] = {}

    def dated(match: re.Match[str]) -> str:
        year, month, day = match.group(1, 2, 3) if match[1] else match.group(6, 5, 4)
        found.setdefault(f"{year}-{int(month):02}-{int(day):02}", match[0])
        return " "

    for number in _NUMBER.finditer(_DATE.sub(dated, text)):
        digits = re.sub(r"\D", "", number[0])
        if every or not number[0].isdigit() or len(digits) >= _IDENTIFIER_DIGITS:
            found.setdefault(digits, number[0])
    return found


def invented(answer: str, question: str) -> list[str]:
    """The values ``answer`` names that ``question`` does not, as ``answer`` writes them: made
    up, or computed, which is the validator's work and not the model's."""
    asked = values(question, every=True)
    return [written for value, written in values(answer, every=False).items() if value not in asked]
