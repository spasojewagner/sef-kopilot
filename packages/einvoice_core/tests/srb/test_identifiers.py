"""PIB, JMBG-shaped PIB and JBKJS checks."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from einvoice_core.srb.identifiers import (
    PIB_SERIALS,
    has_pib_form,
    is_jbkjs,
    is_pib,
    pib_check_digit,
)

serials = st.integers(min_value=PIB_SERIALS.start, max_value=PIB_SERIALS.stop - 1).map(str)


@pytest.mark.parametrize("pib", ["100000016", "100000024", "123456788", "999999995"])
def test_known_valid_pibs(pib: str) -> None:
    assert is_pib(pib)


@pytest.mark.parametrize(
    "value",
    [
        "100000017",  # wrong check digit
        "10000000",  # eight digits
        "1000000088",  # ten digits
        "000000000",  # serial below 10000001
        "100000008",  # serial 10000000 is below the range
        "10000001x",
        "\uff1100000016",  # a full-width digit one is not an ASCII digit
        " 100000016",
        "",
    ],
)
def test_malformed_pibs_are_rejected(value: str) -> None:
    assert not is_pib(value)


@given(serials)
def test_the_computed_check_digit_always_validates(serial: str) -> None:
    assert is_pib(serial + str(pib_check_digit(serial)))


@given(serials, st.integers(min_value=0, max_value=7), st.integers(min_value=1, max_value=9))
def test_any_single_digit_error_is_detected(serial: str, position: int, shift: int) -> None:
    """ISO 7064 MOD 11,10 detects every single-digit substitution."""
    pib = serial + str(pib_check_digit(serial))
    wrong = str((int(pib[position]) + shift) % 10)
    mutated = pib[:position] + wrong + pib[position + 1 :]

    assert not is_pib(mutated)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("100000016", True),
        ("100000017", True),  # the form says nothing about the check digit
        ("0101990710006", True),  # a JMBG used as PIB
        ("10000001", False),
        ("1000000160", False),
        ("010199071000", False),
        ("01019907100xx", False),
        ("RS100000016", False),
        ("", False),
    ],
)
def test_the_form_of_a_pib_is_nine_digits_or_a_jmbg(value: str, expected: bool) -> None:
    assert has_pib_form(value) is expected


@pytest.mark.parametrize(
    ("value", "expected"), [("12345", True), ("1234", False), ("123456", False), ("1234a", False)]
)
def test_jbkjs_is_five_digits(value: str, expected: bool) -> None:
    assert is_jbkjs(value) is expected
