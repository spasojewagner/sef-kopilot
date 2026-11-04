"""Reading amounts of the Serbian extension, which the UBL schema does not validate."""

from __future__ import annotations

from decimal import Decimal

import pytest

from einvoice_core.srb.extension import amount


@pytest.mark.parametrize(
    ("text", "value"),
    [("8400.00", Decimal("8400.00")), ("-1.5", Decimal("-1.5")), ("1E3", Decimal("1E3"))],
)
def test_amounts_are_decimals(text: str, value: Decimal) -> None:
    assert amount(text) == value


@pytest.mark.parametrize("text", [None, "", "8.400,00", "osam hiljada", "NaN", "Infinity"])
def test_anything_else_is_no_amount(text: str | None) -> None:
    assert amount(text) is None
