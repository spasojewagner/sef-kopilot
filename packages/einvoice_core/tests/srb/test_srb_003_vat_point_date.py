"""SRB-003: the VAT point date (BT-7) is not used."""

from __future__ import annotations

from einvoice_core.srb.rules.srb_003_vat_point_date import RULE

from .conftest import Case


def test_satisfied_by_a_vat_point_date_code(case: Case) -> None:
    assert case.violations(RULE) == []


def test_broken_by_a_vat_point_date(case: Case) -> None:
    case.insert(".", "<cbc:TaxPointDate>2026-10-05</cbc:TaxPointDate>", after="cbc:DueDate")

    (violation,) = case.violations(RULE)

    assert violation.xpath == "/ubl:Invoice/cbc:TaxPointDate"
