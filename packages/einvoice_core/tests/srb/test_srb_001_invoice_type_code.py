"""SRB-001: the invoice type code is 380, 381, 383 or 386."""

from __future__ import annotations

import pytest

from einvoice_core.srb.rules.srb_001_invoice_type_code import RULE

from .conftest import Case


@pytest.mark.parametrize("code", ["380", "381", "383", "386"])
def test_satisfied_by_the_four_sef_types(case: Case, code: str) -> None:
    assert case.set_text("cbc:InvoiceTypeCode", code).violations(RULE) == []


def test_satisfied_by_a_credit_note_document(credit_note: Case) -> None:
    assert credit_note.violations(RULE) == []


@pytest.mark.parametrize("code", ["384", "389", "751"])
def test_broken_by_other_type_codes(case: Case, code: str) -> None:
    (violation,) = case.set_text("cbc:InvoiceTypeCode", code).violations(RULE)

    assert violation.xpath == "/ubl:Invoice/cbc:InvoiceTypeCode"
    assert violation.message == (
        f"[SRB-001]-The invoice type code (BT-3) must be one of 380, 381, 383, 386, not '{code}'."
    )
