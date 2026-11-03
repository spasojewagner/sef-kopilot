"""SRB-013: the seller states its VAT registration status."""

from __future__ import annotations

from einvoice_core.srb.rules.srb_013_seller_vat_status import RULE
from einvoice_core.violations import Severity

from .conftest import Case

SELLER = "cac:AccountingSupplierParty/cac:Party"
STATUS = f"{SELLER}/cac:PartyTaxScheme[cac:TaxScheme/cbc:ID = 'RS-VAT-STATUS']"


def test_satisfied_by_a_stated_status(case: Case) -> None:
    assert case.violations(RULE) == []


def test_broken_by_a_missing_status_as_a_warning(case: Case) -> None:
    (violation,) = case.remove(STATUS).violations(RULE)

    assert violation.severity is Severity.WARNING
    assert violation.xpath == f"/ubl:Invoice/{SELLER}"
    assert "VAT registration status (BT-32) is missing" in violation.message


def test_broken_by_a_status_under_another_scheme(case: Case) -> None:
    (violation,) = case.set_text(f"{STATUS}/cac:TaxScheme/cbc:ID", "RS-VAT").violations(RULE)

    assert "VAT registration status (BT-32) is missing" in violation.message
