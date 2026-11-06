"""The guard: the fields a person decides, which no patch may change (ADR-0023)."""

from __future__ import annotations

from collections.abc import Iterable

import pytest

from einvoice_core.guard import (
    AMOUNT,
    COMPANY_IDENTIFIER,
    DATE,
    NUMBER,
    TAX_IDENTIFIER,
    VAT,
    decided,
    protection,
)
from einvoice_core.places import place_of
from einvoice_core.xml import CAC, CBC

SELLER = "/ubl:Invoice/cac:AccountingSupplierParty/cac:Party"
BUYER = "/ubl:Invoice/cac:AccountingCustomerParty/cac:Party"
LINE = "/ubl:Invoice/cac:InvoiceLine[2]"


def refusal(path: str, holds: Iterable[str] = ()) -> str | None:
    place = place_of(path)
    return protection([place.root, *(step.tag for step in place.steps)], place.attribute, holds)


def kind(path: str) -> str | None:
    place = place_of(path)
    return decided([place.root, *(step.tag for step in place.steps)], place.attribute)


@pytest.mark.parametrize(
    ("path", "what", "where"),
    [
        ("/ubl:Invoice/cac:LegalMonetaryTotal/cbc:PayableAmount", AMOUNT, "cac:LegalMonetaryTotal"),
        (f"{LINE}/cbc:LineExtensionAmount", AMOUNT, "cbc:LineExtensionAmount"),
        (f"{LINE}/cac:Price/cbc:PriceAmount", AMOUNT, "cbc:PriceAmount"),
        (f"{LINE}/cac:Price/cbc:BaseQuantity", AMOUNT, "cbc:BaseQuantity"),
        (f"{LINE}/cbc:InvoicedQuantity/@unitCode", AMOUNT, "cbc:InvoicedQuantity"),
        ("/ubl:Invoice/cac:AllowanceCharge/cbc:ChargeIndicator", AMOUNT, "cbc:ChargeIndicator"),
        (
            "/ubl:Invoice/cac:AllowanceCharge/cbc:MultiplierFactorNumeric",
            AMOUNT,
            "cbc:MultiplierFactorNumeric",
        ),
        ("/ubl:Invoice/cbc:DocumentCurrencyCode", AMOUNT, "cbc:DocumentCurrencyCode"),
        ("/ubl:Invoice/cbc:TaxCurrencyCode", AMOUNT, "cbc:TaxCurrencyCode"),
        ("/ubl:Invoice/cbc:PaymentCurrencyCode", AMOUNT, "cbc:PaymentCurrencyCode"),
        ("/ubl:Invoice/cac:TaxExchangeRate/cbc:CalculationRate", AMOUNT, "cac:TaxExchangeRate"),
        # a currency is protected wherever it is said, whatever the element's name
        ("/ubl:Invoice/cac:PrepaidPayment/cbc:ID/@currencyID", AMOUNT, "@currencyID"),
        ("/ubl:Invoice/cac:TaxTotal/cac:TaxSubtotal/cbc:TaxAmount", VAT, "cac:TaxTotal"),
        (
            f"{LINE}/cac:Item/cac:ClassifiedTaxCategory/cbc:Percent",
            VAT,
            "cac:ClassifiedTaxCategory",
        ),
        ("/ubl:Invoice/cac:AllowanceCharge/cac:TaxCategory/cbc:ID", VAT, "cac:TaxCategory"),
        (
            "/ubl:Invoice/cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cbc:TaxExemptionReasonCode",
            VAT,
            "cac:TaxTotal",
        ),
        (f"{SELLER}/cac:PartyTaxScheme[1]/cbc:CompanyID", TAX_IDENTIFIER, "cac:PartyTaxScheme"),
        (f"{SELLER}/cbc:EndpointID", TAX_IDENTIFIER, "cbc:EndpointID"),
        (f"{SELLER}/cbc:EndpointID/@schemeID", TAX_IDENTIFIER, "cbc:EndpointID"),
        (f"{BUYER}/cac:PartyLegalEntity/cbc:CompanyID", COMPANY_IDENTIFIER, "cac:PartyLegalEntity"),
        (
            f"{BUYER}/cac:PartyLegalEntity/cbc:RegistrationName",
            COMPANY_IDENTIFIER,
            "cac:PartyLegalEntity",
        ),
        (f"{BUYER}/cac:PartyIdentification/cbc:ID", COMPANY_IDENTIFIER, "cac:PartyIdentification"),
        (
            "/ubl:Invoice/cac:PaymentMeans/cac:PayeeFinancialAccount/cbc:ID",
            COMPANY_IDENTIFIER,
            "cac:PayeeFinancialAccount",
        ),
        ("/ubl:Invoice/cbc:IssueDate", DATE, "cbc:IssueDate"),
        ("/ubl:Invoice/cbc:DueDate", DATE, "cbc:DueDate"),
        ("/ubl:Invoice/cbc:IssueTime", DATE, "cbc:IssueTime"),
        ("/ubl:Invoice/cac:Delivery/cbc:ActualDeliveryDate", DATE, "cbc:ActualDeliveryDate"),
        ("/ubl:Invoice/cac:InvoicePeriod/cbc:DescriptionCode", DATE, "cac:InvoicePeriod"),
        (
            "/cn:CreditNote/cac:BillingReference/cac:InvoiceDocumentReference/cbc:IssueDate",
            DATE,
            "cbc:IssueDate",
        ),
        ("/ubl:Invoice/cbc:ID", NUMBER, "cbc:ID"),
        ("/cn:CreditNote/cbc:ID", NUMBER, "cbc:ID"),
    ],
)
def test_a_patch_that_touches_what_a_person_decides_is_refused(
    path: str, what: str, where: str
) -> None:
    assert refusal(path) == f"it touches {what} ({where}): a person decides it"
    assert kind(path) == what


@pytest.mark.parametrize(
    "path",
    [
        "/ubl:Invoice/cbc:CustomizationID",
        "/ubl:Invoice/cbc:InvoiceTypeCode",
        "/ubl:Invoice/cbc:Note[2]",
        "/ubl:Invoice/cbc:Note/@languageID",
        "/ubl:Invoice/cbc:BuyerReference",
        f"{BUYER}/cac:PostalAddress/cbc:CityName",
        f"{BUYER}/cac:PostalAddress/cac:Country/cbc:IdentificationCode",
        f"{BUYER}/cac:Contact/cbc:ElectronicMail",
        "/ubl:Invoice/cac:PaymentMeans/cbc:PaymentID",
        "/ubl:Invoice/cac:PaymentMeans/cbc:PaymentMeansCode/@name",
        f"{LINE}/cbc:ID",  # a line's number, not the document's
        f"{LINE}/cac:Item/cbc:Name",
        "/ubl:Invoice/cac:OrderReference/cbc:ID",
    ],
)
def test_a_patch_may_change_how_an_invoice_says_the_rest(path: str) -> None:
    assert refusal(path) is None
    assert kind(path) is None


def test_the_first_protected_element_on_the_way_is_named() -> None:
    path = "/ubl:Invoice/cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cbc:Percent"

    assert refusal(path) == f"it touches {VAT} (cac:TaxTotal): a person decides it"


def test_removing_an_element_touches_what_it_holds() -> None:
    line = [f"{{{CBC}}}ID", f"{{{CBC}}}InvoicedQuantity", f"{{{CBC}}}LineExtensionAmount"]

    assert refusal(LINE, holds=line) == (
        f"it touches {AMOUNT} (cbc:InvoicedQuantity): a person decides it"
    )
    assert refusal("/ubl:Invoice/cac:Delivery", holds=[f"{{{CBC}}}ActualDeliveryDate"]) == (
        f"it touches {DATE} (cbc:ActualDeliveryDate): a person decides it"
    )
    assert refusal(f"{BUYER}/cac:Contact", holds=[f"{{{CBC}}}ElectronicMail"]) is None


def test_what_a_place_is_inside_of_comes_before_what_it_holds() -> None:
    holds = [f"{{{CAC}}}TaxCategory", f"{{{CBC}}}Percent"]

    assert refusal("/ubl:Invoice/cac:TaxTotal/cac:TaxSubtotal", holds=holds) == (
        f"it touches {VAT} (cac:TaxTotal): a person decides it"
    )


def test_the_kind_of_a_place_is_that_of_the_place_not_of_what_it_holds() -> None:
    """What a repairer is shown of a field: a line holds amounts, but is not one."""
    assert kind(LINE) is None
    assert kind(f"{LINE}/cbc:InvoicedQuantity") == AMOUNT
    assert kind(f"{SELLER}/cac:PartyLegalEntity") == COMPANY_IDENTIFIER
