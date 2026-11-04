"""The VAT categories and the Ministry's code list, and how rules find VAT categories."""

from __future__ import annotations

import re
from decimal import Decimal

import pytest

from einvoice_core.srb.rule import Document
from einvoice_core.srb.vat import (
    CATEGORIES,
    CODE_REQUIRED,
    EXEMPTION_CODES,
    breakdown_categories,
    list_key,
    rate,
    tax_categories,
)
from einvoice_core.ubl import build_invoice
from einvoice_core.xml import canonical_xpath

from .conftest import Case

CODE = re.compile(r"PDV-RS-[0-9A-Za-z]+(-[0-9A-Za-z]+)*( \(BN\))?")


def document(case: Case) -> Document:
    return Document(tree=case.tree, invoice=build_invoice(case.root))


def test_the_list_has_the_ministrys_categories_and_codes() -> None:
    assert list(EXEMPTION_CODES) == [
        "S20", "S10", "AE20", "AE10", "Z", "E", "R", "O", "OE", "SS", "N"
    ]  # fmt: skip
    assert sum(len(codes) for codes in EXEMPTION_CODES.values()) == 124
    assert all(CODE.fullmatch(code) for codes in EXEMPTION_CODES.values() for code in codes)
    assert all(len(set(codes)) == len(codes) for codes in EXEMPTION_CODES.values())
    assert EXEMPTION_CODES["S20"] == EXEMPTION_CODES["S10"] == ("PDV-RS-OBJ",)
    assert set(EXEMPTION_CODES["AE20"]) - set(EXEMPTION_CODES["AE10"]) == {"PDV-RS-36b-6"}
    assert set(CATEGORIES) & set(EXEMPTION_CODES) >= CODE_REQUIRED


@pytest.mark.parametrize(
    ("category", "percent", "key"),
    [
        ("S", "20", "S20"),
        ("S", "20.00", "S20"),
        ("AE", "10.0", "AE10"),
        ("S", "15", None),
        ("AE", None, None),
        ("Z", None, "Z"),
        ("N", "0", "N"),
        ("K", "0", None),
    ],
)
def test_the_list_key_combines_code_and_rate(
    category: str, percent: str | None, key: str | None
) -> None:
    assert list_key(category, None if percent is None else Decimal(percent)) == key


def test_the_rate_is_the_percent_as_a_decimal(case: Case) -> None:
    path = "cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory"
    view = document(case)

    assert rate(view, case.element(path)) == Decimal("20")
    assert rate(view, case.remove(f"{path}/cbc:Percent").element(path)) is None


def test_every_vat_category_is_found_with_its_terms(credit_note: Case) -> None:
    found = [(c.where, c.code_term, c.rate_term) for c in tax_categories(document(credit_note))]

    assert found == [
        ("VAT breakdown", "BT-118", "BT-119"),
        ("VAT breakdown", "BT-118", "BT-119"),
        ("document level allowance", "BT-95", "BT-96"),
        ("document level charge", "BT-102", "BT-103"),
        ("invoice line", "BT-151", "BT-152"),
        ("invoice line", "BT-151", "BT-152"),
    ]


RSD_SUBTOTAL = (
    "<cac:TaxSubtotal><cbc:TaxableAmount currencyID='RSD'>106080</cbc:TaxableAmount>"
    "<cbc:TaxAmount currencyID='RSD'>21216</cbc:TaxAmount><cac:TaxCategory><cbc:ID>S</cbc:ID>"
    "<cbc:Percent>20</cbc:Percent><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme>"
    "</cac:TaxCategory></cac:TaxSubtotal>"
)


def test_the_rsd_copy_of_a_foreign_currency_breakdown_is_not_bg_23(credit_note: Case) -> None:
    credit_note.insert("cac:TaxTotal[2]", RSD_SUBTOTAL, after="cbc:TaxAmount")

    assert len(list(tax_categories(document(credit_note)))) == 7
    breakdown = [canonical_xpath(c.element) for c in breakdown_categories(document(credit_note))]
    assert breakdown == [
        "/cn:CreditNote/cac:TaxTotal[1]/cac:TaxSubtotal[1]/cac:TaxCategory",
        "/cn:CreditNote/cac:TaxTotal[1]/cac:TaxSubtotal[2]/cac:TaxCategory",
    ]


def test_without_an_invoice_currency_every_breakdown_counts(credit_note: Case) -> None:
    credit_note.insert("cac:TaxTotal[2]", RSD_SUBTOTAL, after="cbc:TaxAmount")
    credit_note.remove("cbc:DocumentCurrencyCode")

    assert len(list(breakdown_categories(document(credit_note)))) == 3
