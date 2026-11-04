"""Reading amounts of the Serbian extension, which the UBL schema does not validate."""

from __future__ import annotations

from decimal import Decimal

import pytest

from einvoice_core.srb.extension import amount


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("8400.00", Decimal("8400.00")),
        ("-1.5", Decimal("-1.5")),
        (" 12 ", Decimal("12")),
        ("9" * 28, Decimal("9" * 28)),
    ],
)
def test_amounts_are_decimals(text: str, value: Decimal) -> None:
    assert amount(text) == value


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "8.400,00",
        "osam hiljada",
        "NaN",
        "Infinity",
        "1E3",
        "1E+999999",
        "9" * 29,
        "\u0668\u0664\u0660\u0660",  # Arabic-Indic digits
        "\uff18\uff14\uff10\uff10",  # full-width digits
    ],
)
def test_anything_else_is_no_amount(text: str | None) -> None:
    """``xs:decimal`` has no exponent and no digits but 0 to 9, and the checks hold at most 28
    digits exactly. ``Decimal`` would read Arabic-Indic or full-width digits as 8400."""
    assert amount(text) is None
