"""SRB-020: every VAT category code is one SRB-CIUS allows."""

from __future__ import annotations

import pytest

from einvoice_core.srb.rules.srb_020_vat_category_codes import RULE

from .conftest import Case

BREAKDOWN = "cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cbc:ID"
LINE = "cac:InvoiceLine/cac:Item/cac:ClassifiedTaxCategory/cbc:ID"
CYRILLIC_AE = "".join(map(chr, (0x0410, 0x0415)))  # what copying from the Ministry's PDF gives


def test_satisfied_by_standard_rated_categories(case: Case) -> None:
    assert case.violations(RULE) == []


@pytest.mark.parametrize("code", ["Z", "E", "AE", "R", "O", "OE", "SS", "N"])
def test_satisfied_by_every_other_srb_category(case: Case, code: str) -> None:
    assert case.set_text(BREAKDOWN, code).set_text(LINE, code).violations(RULE) == []


def test_satisfied_by_allowances_charges_and_credit_note_lines(credit_note: Case) -> None:
    assert credit_note.violations(RULE) == []


@pytest.mark.parametrize(
    ("code", "hint"),
    [
        ("K", ""),
        ("G", ""),
        ("AE20", " The category AE20 is the code 'AE' with the rate 20 in the rate element."),
        ("S10", " The category S10 is the code 'S' with the rate 10 in the rate element."),
        (CYRILLIC_AE, " It is written with Cyrillic letters; the code is the Latin 'AE'."),
    ],
)
def test_broken_by_a_code_srb_cius_does_not_allow(case: Case, code: str, hint: str) -> None:
    (violation,) = case.set_text(BREAKDOWN, code).violations(RULE)

    assert violation.xpath == f"/ubl:Invoice/{BREAKDOWN}"
    assert violation.message == (
        "[SRB-020]-The VAT breakdown VAT category code (BT-118) must be one of S, Z, E, AE, R, "
        f"O, OE, SS, N; found {code!r}.{hint}"
    )


def test_broken_on_an_invoice_line(case: Case) -> None:
    (violation,) = case.set_text(LINE, "K").violations(RULE)

    assert violation.xpath == f"/ubl:Invoice/{LINE}"
    assert "invoice line VAT category code (BT-151)" in violation.message


def test_broken_on_a_document_level_allowance(credit_note: Case) -> None:
    allowance = "cac:AllowanceCharge[1]/cac:TaxCategory/cbc:ID"

    (violation,) = credit_note.set_text(allowance, "K").violations(RULE)

    assert "document level allowance VAT category code (BT-95)" in violation.message
