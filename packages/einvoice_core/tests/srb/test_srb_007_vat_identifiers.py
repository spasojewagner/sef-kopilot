"""SRB-007: the parties have a VAT identifier RS followed by a PIB."""

from __future__ import annotations

import pytest

from einvoice_core.srb.rules.srb_007_vat_identifiers import RULE

from .conftest import Case

SELLER = "cac:AccountingSupplierParty/cac:Party"
SELLER_VAT = f"{SELLER}/cac:PartyTaxScheme/cbc:CompanyID"
VAT_SCHEME = (
    "<cac:PartyTaxScheme><cbc:CompanyID>RS100000032</cbc:CompanyID>"
    "<cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:PartyTaxScheme>"
)
TAX_REPRESENTATIVE = (
    "<cac:TaxRepresentativeParty>"
    "<cac:PartyName><cbc:Name>Ogledni Zastupnik d.o.o.</cbc:Name></cac:PartyName>"
    "<cac:PostalAddress><cbc:CityName>Novi Sad</cbc:CityName>"
    "<cbc:PostalZone>21000</cbc:PostalZone>"
    "<cac:Country><cbc:IdentificationCode>RS</cbc:IdentificationCode></cac:Country>"
    "</cac:PostalAddress>{tax_scheme}</cac:TaxRepresentativeParty>"
)


def with_tax_representative(case: Case, tax_scheme: str) -> Case:
    fragment = TAX_REPRESENTATIVE.format(tax_scheme=tax_scheme)
    return case.insert(".", fragment, after="cac:AccountingCustomerParty")


def test_satisfied_by_rs_and_a_pib(case: Case) -> None:
    assert case.violations(RULE) == []


def test_satisfied_by_rs_and_a_jmbg(case: Case) -> None:
    assert case.set_text(SELLER_VAT, "RS0101990710006").violations(RULE) == []


def test_satisfied_by_a_tax_representative_with_a_vat_identifier(case: Case) -> None:
    assert with_tax_representative(case, VAT_SCHEME).violations(RULE) == []


@pytest.mark.parametrize(
    "value", ["100000024", "HR100000024", "RS 100000024", "RS10000002", "RS10000002A"]
)
def test_broken_by_a_missing_prefix_or_a_malformed_pib(case: Case, value: str) -> None:
    (violation,) = case.set_text(SELLER_VAT, value).violations(RULE)

    assert violation.xpath == f"/ubl:Invoice/{SELLER_VAT}"
    assert violation.message.endswith(f"found '{value}'.")


def test_broken_by_a_missing_seller_vat_identifier(case: Case) -> None:
    (violation,) = case.remove(f"{SELLER}/cac:PartyTaxScheme").violations(RULE)

    assert violation.xpath == f"/ubl:Invoice/{SELLER}"
    assert "seller VAT identifier (BT-31) is required" in violation.message


def test_broken_by_a_registration_under_another_tax_scheme(case: Case) -> None:
    scheme = f"{SELLER}/cac:PartyTaxScheme/cac:TaxScheme/cbc:ID"

    (violation,) = case.set_text(scheme, "RS-VAT-STATUS").violations(RULE)

    assert "seller VAT identifier (BT-31) is required" in violation.message


def test_broken_by_a_tax_representative_without_a_vat_identifier(case: Case) -> None:
    (violation,) = with_tax_representative(case, "").violations(RULE)

    assert violation.xpath == "/ubl:Invoice/cac:TaxRepresentativeParty"
    assert "tax representative VAT identifier (BT-63) is required" in violation.message


def test_broken_for_the_buyer_too(case: Case) -> None:
    buyer_vat = SELLER_VAT.replace("AccountingSupplierParty", "AccountingCustomerParty")

    (violation,) = case.set_text(buyer_vat, "RS10000001").violations(RULE)

    assert "buyer VAT identifier (BT-48)" in violation.message
