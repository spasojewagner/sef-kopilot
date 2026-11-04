"""Numbers the checks can compute with exactly.

The amounts, quantities, prices and rates of an invoice are ``xs:decimal``: the schema bounds
neither their digits nor, in the Serbian extension, their form. The checks must nevertheless
be exact, like CEN's, which Saxon evaluates with arbitrary precision; Python's default decimal
context keeps 28 digits and rounds beyond them, and refuses outright to round an amount that
needs more to two decimals. So a number may have at most :data:`MAX_DIGITS` digits, far beyond
any real invoice, and every check runs inside :func:`exact`, whose precision holds the sum of
any number of such values and the product of two without rounding.
"""

from __future__ import annotations

import re
from contextlib import AbstractContextManager
from decimal import Context, Decimal, localcontext
from typing import Final

__all__ = ["MAX_DIGITS", "PRECISION", "digits", "exact", "is_decimal", "parse"]

#: The digits a number may have, not counting the leading zeros of its whole part.
MAX_DIGITS: Final = 28
#: Enough for a product of two numbers of :data:`MAX_DIGITS` digits each (wholes and
#: fractions alike), and for summing such products by the million, without rounding.
PRECISION: Final = 128

#: The lexical form of ``xs:decimal``: the digits 0 to 9 only (``\d`` would take any script's,
#: and ``Decimal`` reads them), no exponent, no ``NaN``, no ``Infinity``.
_DECIMAL: Final = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)")


def is_decimal(text: str) -> bool:
    """Whether ``text`` is in the lexical form of ``xs:decimal``."""
    return _DECIMAL.fullmatch(text) is not None


def digits(text: str) -> int:
    """The digits of a number in the form of ``xs:decimal``, without the leading zeros of its
    whole part: ``0012.50`` has four."""
    whole, _, fraction = text.lstrip("+-").partition(".")
    return len(whole.lstrip("0")) + len(fraction)


def parse(text: str | None) -> Decimal | None:
    """``text`` as a number the checks can hold, or ``None`` if it is absent, not in the form
    of ``xs:decimal`` (surrounding whitespace aside), or longer than :data:`MAX_DIGITS`."""
    if text is None:
        return None
    text = text.strip()
    if not is_decimal(text) or digits(text) > MAX_DIGITS:
        return None
    return Decimal(text)


def exact() -> AbstractContextManager[Context]:
    """A decimal context in which the checks' sums and products of parsed numbers are exact."""
    return localcontext(prec=PRECISION)
