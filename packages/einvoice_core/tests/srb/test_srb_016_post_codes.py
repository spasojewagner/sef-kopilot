"""SRB-016: a resident seller and a tax representative give a post code."""

from __future__ import annotations

from einvoice_core.srb.rules.srb_016_post_codes import RULE

from .conftest import Case

SELLER = "cac:AccountingSupplierParty/cac:Party"
TAX_REPRESENTATIVE = (
    "<cac:TaxRepresentativeParty>"
    "<cac:PartyName><cbc:Name>Ogledni Zastupnik d.o.o.</cbc:Name></cac:PartyName>"
    "<cac:PostalAddress><cbc:CityName>Novi Sad</cbc:CityName>{post_code}"
    "<cac:Country><cbc:IdentificationCode>RS</cbc:IdentificationCode></cac:Country>"
    "</cac:PostalAddress></cac:TaxRepresentativeParty>"
)


def with_tax_representative(case: Case, post_code: str) -> Case:
    fragment = TAX_REPRESENTATIVE.format(post_code=post_code)
    return case.insert(".", fragment, after="cac:AccountingCustomerParty")


def test_satisfied_by_post_codes(case: Case) -> None:
    case = with_tax_representative(case, "<cbc:PostalZone>21000</cbc:PostalZone>")

    assert case.violations(RULE) == []


def test_satisfied_by_a_non_resident_seller_without_one(case: Case) -> None:
    case.set_text(f"{SELLER}/cac:PostalAddress/cac:Country/cbc:IdentificationCode", "DE")
    case.remove(f"{SELLER}/cac:PostalAddress/cbc:PostalZone")

    assert case.violations(RULE) == []


def test_broken_by_a_resident_seller_without_one(case: Case) -> None:
    (violation,) = case.remove(f"{SELLER}/cac:PostalAddress/cbc:PostalZone").violations(RULE)

    assert violation.xpath == f"/ubl:Invoice/{SELLER}/cac:PostalAddress"
    assert violation.message == (
        "[SRB-016]-The seller's postal address must give the post code (BT-38)."
    )


def test_broken_by_a_tax_representative_without_one(case: Case) -> None:
    (violation,) = with_tax_representative(case, "").violations(RULE)

    assert violation.xpath == "/ubl:Invoice/cac:TaxRepresentativeParty/cac:PostalAddress"
    assert "(BT-67)" in violation.message
