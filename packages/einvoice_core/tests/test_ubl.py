"""UBL 2.1 → model: exact values on synthetic documents, invariants on official ones."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import BaseModel

from einvoice_core import model
from einvoice_core.ubl import build_invoice, parse_invoice
from einvoice_core.xml import NAMESPACES, ParseError, load_document

from .conftest import official_examples

# --- synthetic invoice: every header field pinned ------------------------------------------


@pytest.fixture(scope="module")
def invoice(synthetic_dir: Path) -> model.Invoice:
    return parse_invoice(synthetic_dir / "srb-minimal-invoice.xml")


def test_invoice_header(invoice: model.Invoice) -> None:
    assert invoice.xpath == "/ubl:Invoice"
    assert invoice.document_type == "Invoice"
    assert (
        invoice.specification_id == "urn:cen.eu:en16931:2017#compliant#urn:mfin.gov.rs:srbdt:2022"
    )
    assert invoice.business_process == "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"
    assert invoice.id == "RF-2026-000123"
    assert invoice.issue_date == date(2026, 10, 5)
    assert invoice.due_date == date(2026, 10, 20)
    assert invoice.type_code == "380"
    assert invoice.currency == "RSD"
    assert invoice.tax_currency is None
    assert invoice.notes == ("Rok za plaćanje je 15 dana od datuma prometa.",)
    assert invoice.buyer_reference == "NAB-77"
    assert invoice.payment_terms == "15 dana"
    assert invoice.period is not None
    assert invoice.period.description_code == "35"
    assert invoice.period.start_date is None
    assert invoice.extension_names == ()


def test_invoice_parties(invoice: model.Invoice) -> None:
    seller = invoice.seller
    assert seller.xpath == "/ubl:Invoice/cac:AccountingSupplierParty"
    assert seller.name == "Primer Softver d.o.o."
    assert seller.trading_name == "Primer Softver"
    assert seller.electronic_address == model.Identifier(value="100000008", scheme="9948")
    assert seller.vat_identifier == "RS100000008"
    assert seller.tax_registration_identifier is None
    assert seller.legal_registration_id == model.Identifier(value="20000006", scheme=None)
    assert seller.address is not None
    assert (
        seller.address.xpath
        == "/ubl:Invoice/cac:AccountingSupplierParty/cac:Party/cac:PostalAddress"
    )
    assert seller.address.city_name == "Čačak"
    assert seller.address.country_code == "RS"
    assert seller.contact is not None
    assert seller.contact.email == "fakture@primer-softver.example"
    assert seller.contact.name is None

    buyer = invoice.buyer
    assert buyer.xpath == "/ubl:Invoice/cac:AccountingCustomerParty"
    assert buyer.name == "Ogledni Kupac d.o.o."
    assert buyer.trading_name is None
    assert buyer.vat_identifier == "RS100000016"
    assert buyer.contact is None
    assert invoice.payee is None
    assert invoice.tax_representative is None


def test_invoice_delivery_and_payment(invoice: model.Invoice) -> None:
    assert invoice.delivery is not None
    assert invoice.delivery.actual_delivery_date == date(2026, 10, 5)
    assert invoice.delivery.address is None

    (payment,) = invoice.payment_instructions
    assert payment.xpath == "/ubl:Invoice/cac:PaymentMeans"
    assert payment.means_code == "30"
    assert payment.means_text == "Prenos na račun"
    assert payment.remittance_information == ("97 12-345678-00123",)
    assert payment.due_date is None
    (account,) = payment.credit_transfers
    assert account.account_id == "160-0000000123456-78"
    assert account.account_name == "Primer Softver d.o.o."
    assert account.service_provider_id is None


def test_invoice_tax_and_totals(invoice: model.Invoice) -> None:
    (tax_total,) = invoice.tax_totals
    assert tax_total.currency == "RSD"
    assert tax_total.tax_amount == Decimal("2400.00")
    (vat,) = invoice.vat_breakdown
    assert vat.xpath == "/ubl:Invoice/cac:TaxTotal/cac:TaxSubtotal"
    assert vat.taxable_amount == Decimal("12000.00")
    assert vat.tax_amount == Decimal("2400.00")
    assert vat.category_code == "S"
    assert vat.rate == Decimal("20")
    assert vat.tax_scheme == "VAT"
    assert vat.exemption_reason is None

    totals = invoice.totals
    assert totals.xpath == "/ubl:Invoice/cac:LegalMonetaryTotal"
    assert totals.currency == "RSD"
    assert totals.line_extension_amount == Decimal("12000.00")
    assert totals.tax_exclusive_amount == Decimal("12000.00")
    assert totals.tax_inclusive_amount == Decimal("14400.00")
    assert totals.payable_amount == Decimal("14400.00")
    assert totals.allowance_total_amount is None
    assert totals.prepaid_amount is None


def test_invoice_line(invoice: model.Invoice) -> None:
    (line,) = invoice.lines
    assert line.xpath == "/ubl:Invoice/cac:InvoiceLine"
    assert line.position == 1
    assert line.id == "1"
    assert line.quantity == model.Quantity(value=Decimal("8"), unit_code="HUR")
    assert line.net_amount == Decimal("12000.00")
    assert line.item.name == "Konsultantski sat"
    assert line.vat is not None
    assert line.vat.category_code == "S"
    assert line.vat.rate == Decimal("20")
    assert line.price is not None
    assert line.price.net_price == Decimal("1500.00")
    assert line.price.base_quantity is None
    assert line.allowances_charges == ()


def test_decimal_text_is_preserved_exactly(invoice: model.Invoice) -> None:
    """``20`` stays ``20`` and ``2400.00`` keeps its two decimals: no float round-trip."""
    (vat,) = invoice.vat_breakdown
    assert str(vat.rate) == "20"
    assert str(vat.tax_amount) == "2400.00"


# --- synthetic credit note: the remaining groups -------------------------------------------


@pytest.fixture(scope="module")
def credit_note(synthetic_dir: Path) -> model.Invoice:
    return parse_invoice(synthetic_dir / "credit-note-full.xml")


def test_credit_note_header_and_references(credit_note: model.Invoice) -> None:
    cn = credit_note
    assert cn.xpath == "/cn:CreditNote"
    assert cn.document_type == "CreditNote"
    assert cn.type_code == "381"
    assert cn.issue_date == date(2026, 11, 2)  # timezone suffix is accepted and dropped
    assert cn.tax_point_date == date(2026, 10, 31)
    assert cn.due_date == date(2026, 11, 30)  # from PaymentMeans/PaymentDueDate
    assert cn.notes == ("#AAI#Storno dela isporuke", "Druga napomena")
    assert cn.currency == "EUR"
    assert cn.tax_currency == "RSD"
    assert cn.accounting_cost == "Projekat 42"
    assert cn.period is not None
    assert (cn.period.start_date, cn.period.end_date) == (date(2026, 10, 1), date(2026, 10, 31))
    assert cn.purchase_order_reference == "PO-1001"
    assert cn.sales_order_reference == "SO-5"
    assert cn.contract_reference == "UG-2025-11"
    assert cn.despatch_advice_reference == "OTP-9"
    assert cn.receiving_advice_reference == "PRJ-3"
    assert cn.tender_or_lot_reference == "TENDER-1"
    assert cn.project_reference == "PRJ-42"
    assert cn.extension_names == ("demo:Marker",)

    (preceding,) = cn.preceding_invoice_references
    assert preceding.id.value == "RF-2026-000123"
    assert preceding.issue_date == date(2026, 10, 5)
    assert preceding.xpath == "/cn:CreditNote/cac:BillingReference/cac:InvoiceDocumentReference"

    invoiced_object, attachment = cn.additional_document_references
    assert invoiced_object.id == model.Identifier(value="OBJ-77", scheme="ABT")
    assert invoiced_object.document_type_code == "130"
    assert attachment.id.value == "PRILOG-1"
    assert attachment.description == "Specifikacija"
    assert attachment.uri == "https://example.invalid/prilog-1"
    assert attachment.embedded_mime_code == "text/csv"
    assert attachment.embedded_filename == "spec.csv"
    assert attachment.embedded_content == "a2xqdWM7dnJlZG5vc3QK"


def test_credit_note_parties(credit_note: model.Invoice) -> None:
    seller = credit_note.seller
    assert seller.identifiers == (
        model.Identifier(value="7300010000001", scheme="0088"),
        model.Identifier(value="SELLER-INTERNAL", scheme=None),
    )
    assert seller.vat_identifier == "RS100000008"
    assert seller.tax_registration_identifier == "100000008"
    assert seller.legal_registration_id == model.Identifier(value="20000006", scheme="0230")
    assert seller.additional_legal_information == "Društvo sa ograničenom odgovornošću"
    assert seller.address is not None
    assert seller.address.additional_street_name == "Sprat 2"
    assert seller.address.address_lines == ("Ulaz B",)
    assert seller.address.country_subentity == "Moravički okrug"
    assert seller.contact is not None
    assert seller.contact.name == "Mira Primer"
    assert seller.contact.telephone == "+381 32 000 000"

    payee = credit_note.payee
    assert payee is not None
    assert payee.xpath == "/cn:CreditNote/cac:PayeeParty"
    assert payee.trading_name == "Primer Faktoring"
    assert payee.identifiers == (model.Identifier(value="7300010000002", scheme="0088"),)
    assert payee.legal_registration_id == model.Identifier(value="20000022", scheme=None)

    representative = credit_note.tax_representative
    assert representative is not None
    assert representative.trading_name == "Poreski Zastupnik"
    assert representative.vat_identifier == "RS123456788"
    assert representative.address is not None
    assert representative.address.city_name == "Novi Sad"


def test_credit_note_delivery_payment_and_allowances(credit_note: model.Invoice) -> None:
    delivery = credit_note.delivery
    assert delivery is not None
    assert delivery.deliver_to_name == "Ogledni Kupac - magacin"
    assert delivery.location_id == model.Identifier(value="7300010000003", scheme="0088")
    assert delivery.actual_delivery_date == date(2026, 10, 15)
    assert delivery.address is not None
    assert delivery.address.xpath == "/cn:CreditNote/cac:Delivery/cac:DeliveryLocation/cac:Address"
    assert delivery.address.city_name == "Kragujevac"

    transfer, direct_debit = credit_note.payment_instructions
    assert transfer.xpath == "/cn:CreditNote/cac:PaymentMeans[1]"
    assert transfer.means_text == "Credit transfer"
    (account,) = transfer.credit_transfers
    assert account.account_id == "RS35160005010000012345"
    assert account.service_provider_id == "BACXRSBG"
    assert direct_debit.means_code == "49"
    assert direct_debit.mandate_reference == "MANDAT-1"
    assert direct_debit.debited_account_id == "RS35160005010000099999"
    assert direct_debit.due_date is None

    allowance, charge = credit_note.allowances_charges
    assert credit_note.allowances == (allowance,)
    assert credit_note.charges == (charge,)
    assert allowance.xpath == "/cn:CreditNote/cac:AllowanceCharge[1]"
    assert allowance.amount == Decimal("100.00")
    assert allowance.base_amount == Decimal("1000.00")
    assert allowance.percentage == Decimal("10")
    assert allowance.vat_category_code == "S"
    assert allowance.vat_rate == Decimal("20")
    assert allowance.reason == "Popust"
    assert allowance.reason_code == "95"
    assert charge.is_charge is True
    assert charge.amount == Decimal("25.00")
    assert charge.base_amount is None


def test_credit_note_two_tax_totals(credit_note: model.Invoice) -> None:
    document, accounting = credit_note.tax_totals
    assert (document.currency, document.tax_amount) == ("EUR", Decimal("181.00"))
    assert (accounting.currency, accounting.tax_amount) == ("RSD", Decimal("21215.20"))
    assert accounting.breakdown == ()
    assert credit_note.document_currency_tax_total is document

    standard, exempt = credit_note.vat_breakdown
    assert standard.xpath == "/cn:CreditNote/cac:TaxTotal[1]/cac:TaxSubtotal[1]"
    assert exempt.category_code == "E"
    assert exempt.rate == Decimal("0")
    assert exempt.exemption_reason_code == "VATEX-EU-G"
    assert exempt.exemption_reason == "Izvoz"

    totals = credit_note.totals
    assert totals.allowance_total_amount == Decimal("100.00")
    assert totals.charge_total_amount == Decimal("25.00")
    assert totals.prepaid_amount == Decimal("6.00")
    assert totals.payable_rounding_amount == Decimal("0.00")
    assert totals.payable_amount == Decimal("1100.00")


def test_credit_note_lines(credit_note: model.Invoice) -> None:
    first, second = credit_note.lines
    assert first.xpath == "/cn:CreditNote/cac:CreditNoteLine[1]"
    assert first.position == 1
    assert first.note == "Vraćeno 4 komada"
    assert first.quantity == model.Quantity(value=Decimal("4"), unit_code="C62")
    assert first.net_amount == Decimal("980.00")
    assert first.accounting_cost == "Projekat 42"
    assert first.order_line_reference == "3"
    assert first.object_identifier == model.Identifier(value="OBJ-LINE-1", scheme="ABT")
    assert first.period is not None
    assert first.period.end_date == date(2026, 10, 15)
    (line_allowance,) = first.allowances
    assert first.charges == ()
    assert line_allowance.amount == Decimal("20.00")
    assert line_allowance.percentage == Decimal("2")
    assert line_allowance.reason == "Količinski popust"
    assert line_allowance.vat_category_code is None

    item = first.item
    assert item.xpath == "/cn:CreditNote/cac:CreditNoteLine[1]/cac:Item"
    assert item.name == "Ventil DN50"
    assert item.description == "Industrijski ventil DN50, mesing"
    assert item.sellers_identifier == "ART-V50"
    assert item.buyers_identifier == "KUP-V50"
    assert item.standard_identifier == model.Identifier(value="07300010000019", scheme="0160")
    assert item.origin_country_code == "RS"
    assert item.classification_codes == (
        model.ClassificationCode(value="42131100", list_id="STI", list_version_id="2.1"),
        model.ClassificationCode(value="V", list_id="CG", list_version_id=None),
    )
    assert item.attributes == (
        model.ItemAttribute(name="Boja", value="mesing"),
        model.ItemAttribute(name="Pritisak", value="PN16"),
    )

    price = first.price
    assert price is not None
    assert price.net_price == Decimal("250.00")
    assert price.discount == Decimal("10.00")
    assert price.gross_price == Decimal("260.00")
    assert price.base_quantity == model.Quantity(value=Decimal("1"), unit_code="C62")

    assert second.position == 2
    assert second.vat is not None
    assert second.vat.category_code == "E"
    assert second.period is None
    assert second.price is not None
    assert second.price.discount is None


# --- official examples: parse, and every XPath in the model resolves to one element -------


def _xpaths(value: object) -> list[str]:
    """Collect every ``xpath`` field anywhere in a model tree."""
    found: list[str] = []
    if isinstance(value, BaseModel):
        for name in type(value).model_fields:
            attribute = getattr(value, name)
            if name == "xpath" and isinstance(attribute, str):
                found.append(attribute)
            else:
                found.extend(_xpaths(attribute))
    elif isinstance(value, tuple | list):
        for item in value:
            found.extend(_xpaths(item))
    return found


_OFFICIAL = official_examples()


@pytest.mark.skipif(not _OFFICIAL, reason="official examples not fetched (run `make rulesets`)")
@pytest.mark.parametrize("path", _OFFICIAL, ids=[p.name for p in _OFFICIAL])
def test_official_example_parses_and_xpaths_resolve(path: Path) -> None:
    tree = load_document(path)
    invoice = build_invoice(tree.getroot())

    assert invoice.id
    assert invoice.lines
    assert invoice.totals.payable_amount is not None
    assert all(line.position == index for index, line in enumerate(invoice.lines, start=1))
    for xpath in _xpaths(invoice):
        selected = tree.xpath(xpath, namespaces=NAMESPACES)
        assert isinstance(selected, list)
        assert len(selected) == 1, xpath


# --- errors: structured, pointing at the element -------------------------------------------


def _wrap(body: str, root: str = "Invoice") -> bytes:
    ns = "Invoice-2" if root == "Invoice" else "CreditNote-2"
    return (
        f'<{root} xmlns="urn:oasis:names:specification:ubl:schema:xsd:{ns}"'
        f' xmlns:cac="{NAMESPACES["cac"]}" xmlns:cbc="{NAMESPACES["cbc"]}">{body}</{root}>'
    ).encode()


_SKELETON = (
    "<cbc:ID>1</cbc:ID><cbc:IssueDate>2026-01-01</cbc:IssueDate>"
    "<cac:AccountingSupplierParty><cac:Party/></cac:AccountingSupplierParty>"
    "<cac:AccountingCustomerParty><cac:Party/></cac:AccountingCustomerParty>"
    "<cac:LegalMonetaryTotal><cbc:PayableAmount>1</cbc:PayableAmount></cac:LegalMonetaryTotal>"
    "<cac:InvoiceLine><cbc:ID>1</cbc:ID><cbc:LineExtensionAmount>1</cbc:LineExtensionAmount>"
    "<cac:Item/></cac:InvoiceLine>"
)


def test_skeleton_with_only_schema_mandatory_elements_parses() -> None:
    invoice = parse_invoice(_wrap(_SKELETON))

    assert invoice.currency is None
    assert invoice.seller.name is None
    assert invoice.tax_totals == ()
    assert invoice.lines[0].quantity is None


def test_unsupported_root_element() -> None:
    with pytest.raises(ParseError, match=r"Invoice or CreditNote, got \{.*Order-2\}Order"):
        parse_invoice(b'<Order xmlns="urn:oasis:names:specification:ubl:schema:xsd:Order-2"/>')


@pytest.mark.parametrize(
    ("body", "message", "xpath"),
    [
        (
            _SKELETON.replace("<cbc:ID>1</cbc:ID><cbc:IssueDate>", "<cbc:IssueDate>", 1),
            "missing required element cbc:ID",
            "/ubl:Invoice",
        ),
        (
            _SKELETON.replace("<cbc:IssueDate>2026-01-01</cbc:IssueDate>", ""),
            "missing required element cbc:IssueDate",
            "/ubl:Invoice",
        ),
        (_SKELETON.replace("2026-01-01", "01.01.2026"), "not a date", "/ubl:Invoice/cbc:IssueDate"),
        (
            _SKELETON.replace("2026-01-01", "2026-02-30"),
            "not a valid calendar date",
            "/ubl:Invoice/cbc:IssueDate",
        ),
        (
            _SKELETON.replace(
                "<cbc:PayableAmount>1</cbc:PayableAmount>",
                "<cbc:PayableAmount>1,5</cbc:PayableAmount>",
            ),
            "not a decimal number: '1,5'",
            "/ubl:Invoice/cac:LegalMonetaryTotal/cbc:PayableAmount",
        ),
        (
            _SKELETON.replace(
                "<cbc:PayableAmount>1</cbc:PayableAmount>",
                "<cbc:PayableAmount>1e3</cbc:PayableAmount>",
            ),
            "not a decimal number: '1e3'",
            "/ubl:Invoice/cac:LegalMonetaryTotal/cbc:PayableAmount",
        ),
        (
            _SKELETON.replace(
                "<cac:LegalMonetaryTotal><cbc:PayableAmount>1</cbc:PayableAmount></cac:LegalMonetaryTotal>",
                "<cac:LegalMonetaryTotal/>",
            ),
            "missing required element cbc:PayableAmount",
            "/ubl:Invoice/cac:LegalMonetaryTotal",
        ),
        (
            _SKELETON.replace(
                "<cac:AccountingCustomerParty><cac:Party/></cac:AccountingCustomerParty>", ""
            ),
            "missing required element cac:AccountingCustomerParty",
            "/ubl:Invoice",
        ),
        (
            _SKELETON.replace(
                "<cac:LegalMonetaryTotal><cbc:PayableAmount>1</cbc:PayableAmount></cac:LegalMonetaryTotal>",
                "",
            ),
            "missing required element cac:LegalMonetaryTotal",
            "/ubl:Invoice",
        ),
        (
            _SKELETON.replace(
                "<cac:AccountingCustomerParty><cac:Party/></cac:AccountingCustomerParty>",
                "<cac:AccountingCustomerParty/>",
            ),
            "missing required element cac:Party",
            "/ubl:Invoice/cac:AccountingCustomerParty",
        ),
        (
            _SKELETON.replace("<cac:Item/>", ""),
            "missing required element cac:Item",
            "/ubl:Invoice/cac:InvoiceLine",
        ),
        (
            _SKELETON.replace("<cac:InvoiceLine><cbc:ID>1</cbc:ID>", "<cac:InvoiceLine>"),
            "missing required element cbc:ID",
            "/ubl:Invoice/cac:InvoiceLine",
        ),
        (
            _SKELETON
            + "<cac:AllowanceCharge><cbc:ChargeIndicator>yes</cbc:ChargeIndicator>"
            + "<cbc:Amount>1</cbc:Amount></cac:AllowanceCharge>",
            "not a boolean: 'yes'",
            "/ubl:Invoice/cac:AllowanceCharge/cbc:ChargeIndicator",
        ),
        (
            _SKELETON + "<cac:AllowanceCharge><cbc:Amount>1</cbc:Amount></cac:AllowanceCharge>",
            "missing required element cbc:ChargeIndicator",
            "/ubl:Invoice/cac:AllowanceCharge",
        ),
        (
            _SKELETON + "<cac:PaymentMeans><cbc:PaymentID>x</cbc:PaymentID></cac:PaymentMeans>",
            "missing required element cbc:PaymentMeansCode",
            "/ubl:Invoice/cac:PaymentMeans",
        ),
        (
            _SKELETON
            + "<cac:AdditionalDocumentReference><cbc:DocumentDescription>x"
            + "</cbc:DocumentDescription></cac:AdditionalDocumentReference>",
            "missing required element cbc:ID",
            "/ubl:Invoice/cac:AdditionalDocumentReference",
        ),
    ],
)
def test_structural_errors_point_at_the_element(body: str, message: str, xpath: str) -> None:
    with pytest.raises(ParseError) as excinfo:
        parse_invoice(_wrap(body))

    assert message in excinfo.value.message
    assert excinfo.value.xpath == xpath


def test_document_without_lines_is_rejected() -> None:
    body = _SKELETON.partition("<cac:InvoiceLine>")[0]
    with pytest.raises(ParseError, match="missing required element cac:InvoiceLine"):
        parse_invoice(_wrap(body))


def test_credit_note_uses_its_own_line_and_quantity_elements() -> None:
    body = _SKELETON.replace("InvoiceLine", "CreditNoteLine").replace(
        "<cbc:LineExtensionAmount>1</cbc:LineExtensionAmount>",
        '<cbc:CreditedQuantity unitCode="C62">2</cbc:CreditedQuantity>'
        "<cbc:LineExtensionAmount>1</cbc:LineExtensionAmount>",
    )
    credit_note = parse_invoice(_wrap(body, root="CreditNote"))

    assert credit_note.document_type == "CreditNote"
    assert credit_note.lines[0].quantity == model.Quantity(value=Decimal("2"), unit_code="C62")


def test_party_tax_scheme_without_company_id_is_ignored() -> None:
    body = _SKELETON.replace(
        "<cac:Party/></cac:AccountingSupplierParty>",
        "<cac:Party><cac:PartyTaxScheme><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme>"
        "</cac:PartyTaxScheme></cac:Party></cac:AccountingSupplierParty>",
    )
    invoice = parse_invoice(_wrap(body))

    assert invoice.seller.vat_identifier is None
    assert invoice.seller.tax_registration_identifier is None


def test_whitespace_only_text_counts_as_absent() -> None:
    body = _SKELETON.replace(
        "<cac:Party/></cac:AccountingSupplierParty>",
        "<cac:Party><cbc:EndpointID>  </cbc:EndpointID></cac:Party></cac:AccountingSupplierParty>",
    )
    invoice = parse_invoice(_wrap(body))

    assert invoice.seller.electronic_address is None


def test_max_bytes_is_passed_through() -> None:
    with pytest.raises(ParseError, match="size limit"):
        parse_invoice(_wrap(_SKELETON), max_bytes=10)
