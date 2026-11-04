"""SRB-012: buyer, payee and a resident seller give a legal registration number."""

from __future__ import annotations

from einvoice_core.srb.rules.srb_012_legal_registration_identifiers import RULE

from .conftest import Case

SELLER = "cac:AccountingSupplierParty/cac:Party"
BUYER = "cac:AccountingCustomerParty/cac:Party"
LEGAL = "cac:PartyLegalEntity/cbc:CompanyID"
PAYEE = (
    "<cac:PayeeParty><cac:PartyName><cbc:Name>Ogledni Faktoring</cbc:Name></cac:PartyName>"
    "<cac:PartyLegalEntity>{company_id}</cac:PartyLegalEntity></cac:PayeeParty>"
)


def with_payee(case: Case, company_id: str) -> Case:
    fragment = PAYEE.format(company_id=company_id)
    return case.insert(".", fragment, after="cac:AccountingCustomerParty")


def test_satisfied_by_registration_numbers_without_a_scheme(case: Case) -> None:
    assert case.violations(RULE) == []


def test_satisfied_by_a_payee_with_a_registration_number(case: Case) -> None:
    case = with_payee(case, "<cbc:CompanyID>20000022</cbc:CompanyID>")

    assert case.violations(RULE) == []


def test_satisfied_by_a_non_resident_seller_without_one(case: Case) -> None:
    case.set_text(f"{SELLER}/cac:PostalAddress/cac:Country/cbc:IdentificationCode", "DE")
    case.remove(f"{SELLER}/{LEGAL}")

    assert case.violations(RULE) == []


def test_broken_by_a_resident_seller_without_one(case: Case) -> None:
    (violation,) = case.remove(f"{SELLER}/{LEGAL}").violations(RULE)

    assert violation.xpath == f"/ubl:Invoice/{SELLER}/cac:PartyLegalEntity"
    assert "seller legal registration identifier (BT-30) is required" in violation.message


def test_broken_by_a_buyer_without_one(case: Case) -> None:
    (violation,) = case.set_text(f"{BUYER}/{LEGAL}", " ").violations(RULE)

    assert "buyer legal registration identifier (BT-47) is required" in violation.message


def test_broken_by_a_payee_without_one(case: Case) -> None:
    (violation,) = with_payee(case, "").violations(RULE)

    assert violation.xpath == "/ubl:Invoice/cac:PayeeParty/cac:PartyLegalEntity"
    assert "payee legal registration identifier (BT-61) is required" in violation.message


def test_broken_by_a_scheme_identifier(case: Case) -> None:
    (violation,) = case.set_attribute(f"{BUYER}/{LEGAL}", "schemeID", "0230").violations(RULE)

    assert violation.xpath == f"/ubl:Invoice/{BUYER}/{LEGAL}/@schemeID"
    assert violation.message.endswith("found '0230'.")
