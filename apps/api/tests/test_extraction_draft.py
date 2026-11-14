"""A UBL invoice drafted in code from an invoice's fields: what a known invoice's fields give back
is valid, every element comes from a field or from SRB-CIUS, and nothing is filled in."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from lxml import etree

from einvoice_core.pipeline import validate
from einvoice_core.ubl import parse_invoice
from einvoice_core.xml import NAMESPACES
from sef_api.extraction.draft import draft
from sef_api.extraction.fields import (
    InvoiceFields,
    Line,
    Party,
    Payment,
    Totals,
    VatSubtotal,
    fields_of,
)

SYNTHETIC = Path(__file__).resolve().parents[3] / "fixtures" / "invoices" / "synthetic"


def read(document: bytes) -> etree._Element:
    return etree.fromstring(document)


def texts(root: etree._Element, path: str) -> list[str]:
    return [str(element.text) for element in root.xpath(path, namespaces=NAMESPACES)]


@pytest.mark.parametrize("name", ["srb-minimal-invoice", "srb-final-invoice"])
def test_the_fields_of_a_valid_invoice_draft_a_valid_invoice(name: str) -> None:
    fields = fields_of(parse_invoice(SYNTHETIC / f"{name}.xml"))

    report = validate(draft(fields), profile="srb")

    assert report.valid, [violation.rule_id for violation in report.violations]
    assert report.violations == ()


def test_a_draft_reads_back_as_the_fields_it_was_made_of() -> None:
    fields = fields_of(parse_invoice(SYNTHETIC / "srb-minimal-invoice.xml"))

    assert fields_of(parse_invoice(draft(fields))) == fields


def test_the_same_fields_always_draft_the_same_document() -> None:
    fields = fields_of(parse_invoice(SYNTHETIC / "srb-minimal-invoice.xml"))

    assert draft(fields) == draft(fields_of(parse_invoice(SYNTHETIC / "srb-minimal-invoice.xml")))
    assert draft(fields).startswith(b"<?xml version='1.0' encoding='UTF-8'?>\n<Invoice ")


def test_what_srb_cius_fixes_is_written_and_identifiers_in_its_schemes() -> None:
    root = read(
        draft(
            InvoiceFields(
                delivery_date="2026-10-05",
                seller=Party(tax_id="RS100000024"),
                seller_in_vat_register=False,
                buyer=Party(tax_id="100000016"),
                payment=Payment(account="160-1-78", model="97", reference="12-345"),
            )
        )
    )

    assert texts(root, "cbc:CustomizationID") == [
        "urn:cen.eu:en16931:2017#compliant#urn:mfin.gov.rs:srbdt:2022"
    ]
    assert texts(root, "cac:InvoicePeriod/cbc:DescriptionCode") == ["35"]
    seller = "cac:AccountingSupplierParty/cac:Party"
    assert texts(root, f"{seller}/cbc:EndpointID[@schemeID='9948']") == ["100000024"]
    assert texts(root, f"{seller}/cac:PartyTaxScheme/cbc:CompanyID") == ["RS100000024", "NO-VAT"]
    assert texts(
        root, "cac:AccountingCustomerParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID"
    ) == ["RS100000016"]
    assert texts(root, "cac:PaymentMeans/cbc:PaymentMeansCode") == ["30"]
    assert texts(root, "cac:PaymentMeans/cbc:PaymentID") == ["(mod97) 12-345"]
    assert texts(root, "cac:PaymentMeans/cac:PayeeFinancialAccount/cbc:ID") == ["160-1-78"]


def test_without_a_date_of_supply_the_vat_point_is_the_date_of_issue() -> None:
    root = read(draft(InvoiceFields(issue_date="2026-10-05")))

    assert texts(root, "cac:InvoicePeriod/cbc:DescriptionCode") == ["3"]
    assert root.find("cac:Delivery", NAMESPACES) is None


def test_a_reference_without_a_model_is_written_as_read() -> None:
    root = read(draft(InvoiceFields(payment=Payment(reference="RF-2026-000123"))))

    assert texts(root, "cac:PaymentMeans/cbc:PaymentID") == ["RF-2026-000123"]


def test_nothing_is_computed_or_filled_in() -> None:
    fields = InvoiceFields(
        lines=[Line(name="Konsultantski sat", quantity="8", unit_price="1500.00")],
        totals=Totals(payable="14400.00"),
    )

    root = read(draft(fields))

    line = root.find("cac:InvoiceLine", NAMESPACES)
    assert line is not None
    assert line.find("cbc:LineExtensionAmount", NAMESPACES) is None
    assert line.find("cac:Item/cac:ClassifiedTaxCategory", NAMESPACES) is None
    assert line.xpath("cbc:InvoicedQuantity/@unitCode", namespaces=NAMESPACES) == []
    assert root.find("cac:TaxTotal", NAMESPACES) is None
    assert texts(root, "cac:LegalMonetaryTotal/*") == ["14400.00"]
    for absent in (
        "cbc:ID",
        "cbc:IssueDate",
        "cbc:DueDate",
        "cbc:InvoiceTypeCode",
        "cac:PaymentMeans",
    ):
        assert root.find(absent, NAMESPACES) is None, absent
    # The validator says what is missing; that is its job, not the draft's.
    (missing,) = validate(draft(fields), profile="srb").violations
    assert (missing.rule_id, missing.layer) == ("XSD", "xsd")
    assert "ID" in missing.message


def test_amounts_are_in_the_invoice_s_currency_and_written_as_read() -> None:
    fields = InvoiceFields(
        currency="EUR",
        lines=[Line(net_amount="100.5", unit_price="100.50")],
        totals=Totals(tax="20.1", payable="120.60"),
    )

    root = read(draft(fields))

    assert texts(root, "cbc:DocumentCurrencyCode") == ["EUR"]
    assert set(root.xpath("//@currencyID", namespaces=NAMESPACES)) == {"EUR"}
    assert texts(root, "cac:InvoiceLine/cbc:LineExtensionAmount") == ["100.5"]
    assert texts(root, "cac:TaxTotal/cbc:TaxAmount") == ["20.1"]


def test_a_credit_note_is_drafted_as_one() -> None:
    fields = InvoiceFields(
        type_code="381",
        number="KO-2026-7",
        issue_date="2026-11-02",
        due_date="2026-11-30",
        lines=[Line(name="Povrat", quantity="1", unit="H87", net_amount="100.00")],
        totals=Totals(payable="100.00"),
        payment=Payment(account="160-1-78"),
    )

    root = read(draft(fields))

    assert etree.QName(root).localname == "CreditNote"
    assert (
        etree.QName(root).namespace == "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"
    )
    assert texts(root, "cbc:CreditNoteTypeCode") == ["381"]
    assert root.find("cbc:DueDate", NAMESPACES) is None
    assert texts(root, "cac:PaymentMeans/cbc:PaymentDueDate") == ["2026-11-30"]
    assert texts(root, "cac:CreditNoteLine/cbc:CreditedQuantity") == ["1"]
    report = validate(draft(fields), profile="srb")
    assert "xsd" not in {violation.layer for violation in report.violations}


#: The fields without which a draft fails the UBL schema, each emptied alone from a valid
#: invoice's fields, by the place the web's form names them (`requiredIn` in apps/web): the form
#: asks for these, and for a line at least, before it has an invoice drafted, so a change here
#: is a change there too.
SCHEMA_REQUIRED = frozenset(
    {
        "number",
        "issue_date",
        "totals.tax",
        "totals.payable",
        "lines.0.net_amount",
        "vat_breakdown.0.tax_amount",
    }
)


def _emptied(fields: InvoiceFields, place: str) -> InvoiceFields:
    data = fields.model_dump()
    *path, last = place.split(".")
    node: Any = data
    for part in path:
        node = node[int(part)] if part.isdigit() else node[part]
    node[last] = None
    return InvoiceFields.model_validate(data)


def _fails_schema(fields: InvoiceFields) -> bool:
    report = validate(draft(fields), profile="srb")
    return any(violation.layer in ("xml", "xsd") for violation in report.violations)


def test_the_fields_a_draft_fails_the_schema_without_are_those_the_form_asks_for() -> None:
    fields = fields_of(parse_invoice(SYNTHETIC / "srb-final-invoice.xml"))
    places = [
        "type_code",
        "number",
        "issue_date",
        "due_date",
        "delivery_date",
        "currency",
        "buyer_reference",
        *(f"seller.{key}" for key in Party.model_fields),
        *(f"buyer.{key}" for key in Party.model_fields),
        *(f"totals.{key}" for key in Totals.model_fields),
        *(f"lines.0.{key}" for key in Line.model_fields),
        *(f"vat_breakdown.0.{key}" for key in VatSubtotal.model_fields),
        *(f"payment.{key}" for key in Payment.model_fields),
    ]

    failing = {place for place in places if _fails_schema(_emptied(fields, place))}

    assert failing == SCHEMA_REQUIRED
    assert _fails_schema(fields.model_copy(update={"lines": []}))
    assert not _fails_schema(fields)
