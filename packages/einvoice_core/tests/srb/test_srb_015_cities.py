"""SRB-015: seller, buyer and tax representative addresses name the city."""

from __future__ import annotations

import pytest

from einvoice_core.srb.rules.srb_015_cities import RULE

from .conftest import Case

SELLER = "cac:AccountingSupplierParty/cac:Party"
BUYER = "cac:AccountingCustomerParty/cac:Party"
TAX_REPRESENTATIVE = (
    "<cac:TaxRepresentativeParty>"
    "<cac:PartyName><cbc:Name>Ogledni Zastupnik d.o.o.</cbc:Name></cac:PartyName>"
    "<cac:PostalAddress>{city}<cbc:PostalZone>21000</cbc:PostalZone>"
    "<cac:Country><cbc:IdentificationCode>RS</cbc:IdentificationCode></cac:Country>"
    "</cac:PostalAddress></cac:TaxRepresentativeParty>"
)


def with_tax_representative(case: Case, city: str) -> Case:
    fragment = TAX_REPRESENTATIVE.format(city=city)
    return case.insert(".", fragment, after="cac:AccountingCustomerParty")


def test_satisfied_by_named_cities(case: Case) -> None:
    assert case.violations(RULE) == []


def test_satisfied_by_a_tax_representative_with_a_city(case: Case) -> None:
    case = with_tax_representative(case, "<cbc:CityName>Novi Sad</cbc:CityName>")

    assert case.violations(RULE) == []


@pytest.mark.parametrize(("party", "term"), [(SELLER, "BT-37"), (BUYER, "BT-52")])
def test_broken_by_a_missing_city(case: Case, party: str, term: str) -> None:
    (violation,) = case.remove(f"{party}/cac:PostalAddress/cbc:CityName").violations(RULE)

    assert violation.xpath == f"/ubl:Invoice/{party}/cac:PostalAddress"
    assert violation.message.endswith(f"must name the city ({term}).")


def test_broken_by_an_empty_city(case: Case) -> None:
    (violation,) = case.set_text(f"{SELLER}/cac:PostalAddress/cbc:CityName", "").violations(RULE)

    assert "seller's postal address must name the city (BT-37)" in violation.message


def test_broken_by_a_tax_representative_without_a_city(case: Case) -> None:
    (violation,) = with_tax_representative(case, "").violations(RULE)

    assert violation.xpath == "/ubl:Invoice/cac:TaxRepresentativeParty/cac:PostalAddress"
    assert "(BT-66)" in violation.message
