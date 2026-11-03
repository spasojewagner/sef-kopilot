"""Serbian identifiers that SRB-CIUS invoices carry: PIB, JMBG-shaped PIB and JBKJS.

* **PIB** (poreski identifikacioni broj, tax identification number): nine digits, an
  eight-digit serial number from 10000001 to 99999999 followed by a check digit computed over
  the serial with ISO 7064 MOD 11,10 (Pravilnik o poreskom identifikacionom broju, Article 2,
  paragraphs 5 to 8).
* For resident natural persons who are not entrepreneurs the PIB is their 13-digit JMBG
  (same Article, paragraph 9); only its form is checked here, because the JMBG check digit is
  defined outside the rulebook.
* **JBKJS** (jedinstveni broj korisnika javnih sredstava, public-funds user number): five
  digits, carried with the prefix ``JBKJS:`` (SRB-CIUS, BT-29).

The checks are deliberately strict about form (ASCII digits only, exact lengths) and say
nothing about whether a number is assigned: only the Tax Administration and the Treasury
registers know that, and SEF checks them when an invoice is sent.
"""

from __future__ import annotations

import re
from typing import Final

__all__ = [
    "PIB_DIGITS",
    "PIB_SERIALS",
    "has_pib_form",
    "is_jbkjs",
    "is_pib",
    "pib_check_digit",
]

_DIGITS: Final = re.compile(r"[0-9]+")

#: The length of a PIB the rulebook assigns (a JMBG used as PIB has thirteen digits).
PIB_DIGITS: Final = 9
#: The serial numbers the rulebook assigns: the first eight digits of a nine-digit PIB.
PIB_SERIALS: Final = range(10_000_001, 100_000_000)
_JMBG_DIGITS: Final = 13


def _digits(value: str, length: int) -> bool:
    return len(value) == length and _DIGITS.fullmatch(value) is not None


def pib_check_digit(serial: str) -> int:
    """The ISO 7064 MOD 11,10 check digit for an eight-digit PIB serial number."""
    product = 10
    for character in serial:
        total = (int(character) + product) % 10 or 10
        product = (2 * total) % 11
    return (11 - product) % 10


def has_pib_form(value: str) -> bool:
    """Whether ``value`` has the form of a PIB: nine ASCII digits, or thirteen for a JMBG."""
    return _digits(value, PIB_DIGITS) or _digits(value, _JMBG_DIGITS)


def is_pib(value: str) -> bool:
    """Whether ``value`` is a nine-digit PIB the rulebook can assign: serial and check digit."""
    if not _digits(value, PIB_DIGITS):
        return False
    serial = value[:8]
    return int(serial) in PIB_SERIALS and int(value[8]) == pib_check_digit(serial)


def is_jbkjs(value: str) -> bool:
    """Whether ``value`` is a five-digit public-funds user number (without the prefix)."""
    return _digits(value, 5)
