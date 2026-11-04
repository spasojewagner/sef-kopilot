"""SRB-017: the buyer's address gives a post code."""

from __future__ import annotations

from einvoice_core.srb.rules.srb_017_buyer_post_code import RULE
from einvoice_core.violations import Severity

from .conftest import Case

BUYER = "cac:AccountingCustomerParty/cac:Party"


def test_satisfied_by_a_post_code(case: Case) -> None:
    assert case.violations(RULE) == []


def test_broken_by_a_missing_post_code_as_a_warning(case: Case) -> None:
    (violation,) = case.remove(f"{BUYER}/cac:PostalAddress/cbc:PostalZone").violations(RULE)

    assert violation.severity is Severity.WARNING
    assert violation.xpath == f"/ubl:Invoice/{BUYER}/cac:PostalAddress"
    assert (
        violation.message == "[SRB-017]-The buyer's postal address must give the post code (BT-53)."
    )
