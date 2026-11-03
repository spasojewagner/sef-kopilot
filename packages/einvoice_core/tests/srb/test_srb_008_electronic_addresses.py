"""SRB-008: seller and buyer electronic addresses are a PIB with scheme 9948."""

from __future__ import annotations

import pytest

from einvoice_core.srb.rules.srb_008_electronic_addresses import RULE

from .conftest import Case

SELLER = "cac:AccountingSupplierParty/cac:Party"


def test_satisfied_by_pibs_with_scheme_9948(case: Case) -> None:
    assert case.violations(RULE) == []


def test_satisfied_by_a_jmbg_with_scheme_9948(case: Case) -> None:
    assert case.set_text(f"{SELLER}/cbc:EndpointID", "0101990710006").violations(RULE) == []


def test_broken_by_a_missing_address(case: Case) -> None:
    (violation,) = case.remove(f"{SELLER}/cbc:EndpointID").violations(RULE)

    assert violation.xpath == f"/ubl:Invoice/{SELLER}"
    assert "seller electronic address (BT-34) is required" in violation.message


def test_broken_by_another_scheme(case: Case) -> None:
    (violation,) = case.set_attribute(f"{SELLER}/cbc:EndpointID", "schemeID", "0088").violations(
        RULE
    )

    assert violation.xpath == f"/ubl:Invoice/{SELLER}/cbc:EndpointID/@schemeID"


@pytest.mark.parametrize("value", ["10000002", "RS100000024", "fakture@primer.example"])
def test_broken_by_a_value_that_is_not_a_pib(case: Case, value: str) -> None:
    (violation,) = case.set_text(f"{SELLER}/cbc:EndpointID", value).violations(RULE)

    assert violation.xpath == f"/ubl:Invoice/{SELLER}/cbc:EndpointID"
    assert violation.message.endswith(f"found '{value}'.")
