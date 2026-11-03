"""SRB-009: every nine-digit PIB has a serial number in range and a valid check digit."""

from __future__ import annotations

import pytest

from einvoice_core.srb.rules.srb_009_pib_check_digits import RULE

from .conftest import Case

SELLER = "cac:AccountingSupplierParty/cac:Party"
BUYER = "cac:AccountingCustomerParty/cac:Party"
VAT = "cac:PartyTaxScheme/cbc:CompanyID"


def test_satisfied_by_assignable_pibs(case: Case) -> None:
    assert case.violations(RULE) == []


@pytest.mark.parametrize("value", ["RS0101990710006", "RS10000002", "100000025"])
def test_satisfied_by_values_whose_form_other_rules_judge(case: Case, value: str) -> None:
    """A JMBG, a short number or a missing prefix is SRB-007's business, not this rule's."""
    assert case.set_text(f"{SELLER}/{VAT}", value).violations(RULE) == []


def test_broken_by_a_mistyped_check_digit(case: Case) -> None:
    (violation,) = case.set_text(f"{SELLER}/{VAT}", "RS100000025").violations(RULE)

    assert violation.xpath == f"/ubl:Invoice/{SELLER}/{VAT}"
    assert violation.message == (
        "[SRB-009]-The PIB 100000025 in the seller VAT identifier (BT-31) cannot exist: its "
        "last digit must be the check digit of 10000002, which is 4, not 5."
    )


def test_broken_by_a_serial_number_below_the_range(case: Case) -> None:
    (violation,) = case.set_text(f"{BUYER}/cbc:EndpointID", "100000008").violations(RULE)

    assert violation.xpath == f"/ubl:Invoice/{BUYER}/cbc:EndpointID"
    assert "first eight digits of a PIB run from 10000001 to 99999999" in violation.message


def test_broken_in_every_place_a_pib_appears(case: Case) -> None:
    case.set_text(f"{SELLER}/cbc:EndpointID", "123456789")
    case.set_text(f"{SELLER}/{VAT}", "RS123456789")
    case.set_text(f"{BUYER}/cbc:EndpointID", "987654321")
    case.set_text(f"{BUYER}/{VAT}", "RS987654321")

    terms = [
        violation.message.split(" in the ")[1].split(" cannot")[0]
        for violation in case.violations(RULE)
    ]

    assert terms == [
        "seller VAT identifier (BT-31)",
        "seller electronic address (BT-34)",
        "buyer VAT identifier (BT-48)",
        "buyer electronic address (BT-49)",
    ]
