"""SRB-019: a payment model in the remittance information is written (modNN) reference."""

from __future__ import annotations

import pytest

from einvoice_core.srb.rules.srb_019_payment_model import RULE

from .conftest import Case

PAYMENT_ID = "cac:PaymentMeans/cbc:PaymentID"


def test_satisfied_by_the_prescribed_notation(case: Case) -> None:
    assert case.violations(RULE) == []


@pytest.mark.parametrize("value", ["12-345678-00123", "97 12-345678-00123", "Faktura RF-2026"])
def test_satisfied_by_a_reference_without_a_model(case: Case, value: str) -> None:
    assert case.set_text(PAYMENT_ID, value).violations(RULE) == []


@pytest.mark.parametrize(
    "value",
    [
        "(mod 97) 12-345678-00123",
        "(mod97)12-345678-00123",
        "(mod97)  12-345678-00123",
        "(MOD97) 12-345678-00123",
        "mod97 12-345678-00123",
        "(mod9) 12-345678-00123",
        "(mod97)",
    ],
)
def test_broken_by_another_notation(case: Case, value: str) -> None:
    (violation,) = case.set_text(PAYMENT_ID, value).violations(RULE)

    assert violation.xpath == f"/ubl:Invoice/{PAYMENT_ID}"
    assert violation.message.endswith(f"found '{value}'.")
