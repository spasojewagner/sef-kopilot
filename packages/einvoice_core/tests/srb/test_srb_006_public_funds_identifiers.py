"""SRB-006: a public-funds user has one identifier JBKJS:<five digits>, without a scheme."""

from __future__ import annotations

from einvoice_core.srb.rules.srb_006_public_funds_identifiers import RULE

from .conftest import Case

BUYER = "cac:AccountingCustomerParty/cac:Party"


def _buyer_identifier(case: Case, identifier: str) -> Case:
    return case.insert(
        BUYER,
        f"<cac:PartyIdentification>{identifier}</cac:PartyIdentification>",
        after="cbc:EndpointID",
    )


def test_satisfied_by_a_party_without_public_funds(case: Case) -> None:
    assert case.violations(RULE) == []


def test_satisfied_by_a_jbkjs_without_a_scheme(case: Case) -> None:
    _buyer_identifier(case, "<cbc:ID>JBKJS:12345</cbc:ID>")

    assert case.violations(RULE) == []


def test_broken_by_a_jbkjs_that_is_not_five_digits(case: Case) -> None:
    (violation,) = _buyer_identifier(case, "<cbc:ID>JBKJS:1234</cbc:ID>").violations(RULE)

    assert violation.xpath == f"/ubl:Invoice/{BUYER}/cac:PartyIdentification/cbc:ID"
    assert "buyer identifier (BT-46) 'JBKJS:1234'" in violation.message


def test_broken_by_a_jbkjs_with_a_scheme(case: Case) -> None:
    _buyer_identifier(case, '<cbc:ID schemeID="0088">JBKJS:12345</cbc:ID>')

    (violation,) = case.violations(RULE)

    assert violation.xpath == f"/ubl:Invoice/{BUYER}/cac:PartyIdentification/cbc:ID/@schemeID"


def test_broken_by_a_second_jbkjs(case: Case) -> None:
    _buyer_identifier(case, "<cbc:ID>JBKJS:12345</cbc:ID>")
    _buyer_identifier(case, "<cbc:ID>JBKJS:54321</cbc:ID>")

    (violation,) = case.violations(RULE)

    assert violation.xpath == f"/ubl:Invoice/{BUYER}/cac:PartyIdentification[2]/cbc:ID"
    assert "extra" in violation.message
