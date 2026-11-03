"""SRB-014: the seller's VAT registration status is VAT or NO-VAT."""

from __future__ import annotations

import pytest

from einvoice_core.srb.rules.srb_014_seller_vat_status_value import RULE

from .conftest import Case

SELLER = "cac:AccountingSupplierParty/cac:Party"
STATUS = f"{SELLER}/cac:PartyTaxScheme[cac:TaxScheme/cbc:ID = 'RS-VAT-STATUS']/cbc:CompanyID"


@pytest.mark.parametrize("value", ["VAT", "NO-VAT"])
def test_satisfied_by_either_status(case: Case, value: str) -> None:
    assert case.set_text(STATUS, value).violations(RULE) == []


def test_satisfied_when_the_status_is_absent(case: Case) -> None:
    """Its absence is SRB-013's business."""
    case.remove(f"{SELLER}/cac:PartyTaxScheme[cac:TaxScheme/cbc:ID = 'RS-VAT-STATUS']")

    assert case.violations(RULE) == []


@pytest.mark.parametrize("value", ["PDV", "vat", "NOVAT", "RS100000024"])
def test_broken_by_another_value(case: Case, value: str) -> None:
    (violation,) = case.set_text(STATUS, value).violations(RULE)

    assert violation.xpath == f"/ubl:Invoice/{SELLER}/cac:PartyTaxScheme[2]/cbc:CompanyID"
    assert violation.message.endswith(f"found '{value}'.")
