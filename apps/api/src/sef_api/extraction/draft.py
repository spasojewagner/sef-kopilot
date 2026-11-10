"""A UBL 2.1 invoice drafted, in code, from an invoice's fields as a person confirmed them
(ADR-0062).

The model reads a document into fields; it never writes UBL. This module does, deterministically:
the same fields always make the same document, and every element comes from a field, or from
SRB-CIUS where the profile fixes it (the specification identifier, the payment means, the
schemes of the identifiers). Nothing is computed or filled in: a field left empty leaves its
element out, an amount is written as it was read, and the validator then says what is missing
or does not add up, which is its job. A credit note (type code 381) is written as a UBL credit
note.

What the fields do not carry is left for the validator to report and a person to add: the
references a credit note or a final invoice needs to the invoices before it, the VAT in dinars
of an invoice in another currency, and the Serbian extension (SrbDtExt).
"""

from __future__ import annotations

from typing import Final

from lxml import etree

from einvoice_core.srb.codes import SPECIFICATION_IDENTIFIER
from einvoice_core.xml import CAC, CBC, CN, UBL
from sef_api.extraction.fields import InvoiceFields, Line, Party

__all__ = ["PEPPOL_PROFILE", "draft"]

#: BT-23, the business process, as the Ministry's examples give it.
PEPPOL_PROFILE: Final = "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"
#: The scheme of an electronic address that is a PIB (SRB-008).
PIB_SCHEME: Final = "9948"
#: BT-8: the VAT point is the date of supply where the document gives one, the date of issue
#: otherwise.
SUPPLY_DATE, ISSUE_DATE = "35", "3"
#: BT-81: payment by credit transfer, as a Serbian invoice is paid.
CREDIT_TRANSFER: Final = "30"

_NAMESPACES: Final[dict[str | None, str]] = {"cac": CAC, "cbc": CBC}


class _Writer:
    """Elements appended in the order the UBL schema gives them."""

    def __init__(self, root: etree._Element) -> None:
        self.root = root

    def basic(
        self, parent: etree._Element, name: str, value: str | None, **attributes: str
    ) -> None:
        if value is None:
            return
        element = etree.SubElement(parent, f"{{{CBC}}}{name}", attributes)
        element.text = value

    def aggregate(self, parent: etree._Element, name: str) -> etree._Element:
        element: etree._Element = etree.SubElement(parent, f"{{{CAC}}}{name}")
        return element


def _tax_id(value: str | None) -> str | None:
    """A PIB without the RS a VAT identifier writes before it."""
    if value is None:
        return None
    return value[2:].strip() if value.upper().startswith("RS") else value


def _party(write: _Writer, parent: etree._Element, party: Party, *, vat_status: str | None) -> None:
    holder = write.aggregate(parent, "Party")
    pib = _tax_id(party.tax_id)
    write.basic(holder, "EndpointID", pib, schemeID=PIB_SCHEME)
    if party.name is not None:
        write.basic(write.aggregate(holder, "PartyName"), "Name", party.name)
    if any(
        value is not None for value in (party.street, party.city, party.postal_code, party.country)
    ):
        address = write.aggregate(holder, "PostalAddress")
        write.basic(address, "StreetName", party.street)
        write.basic(address, "CityName", party.city)
        write.basic(address, "PostalZone", party.postal_code)
        if party.country is not None:
            write.basic(write.aggregate(address, "Country"), "IdentificationCode", party.country)
    if pib is not None:
        scheme = write.aggregate(holder, "PartyTaxScheme")
        write.basic(scheme, "CompanyID", f"RS{pib}")
        write.basic(write.aggregate(scheme, "TaxScheme"), "ID", "VAT")
    if vat_status is not None:
        scheme = write.aggregate(holder, "PartyTaxScheme")
        write.basic(scheme, "CompanyID", vat_status)
        write.basic(write.aggregate(scheme, "TaxScheme"), "ID", "RS-VAT-STATUS")
    if party.name is not None or party.company_id is not None:
        entity = write.aggregate(holder, "PartyLegalEntity")
        write.basic(entity, "RegistrationName", party.name)
        write.basic(entity, "CompanyID", party.company_id)
    if party.email is not None:
        write.basic(write.aggregate(holder, "Contact"), "ElectronicMail", party.email)


def _category(
    write: _Writer, parent: etree._Element, name: str, category: str | None, rate: str | None
) -> None:
    if category is None and rate is None:
        return
    holder = write.aggregate(parent, name)
    write.basic(holder, "ID", category)
    write.basic(holder, "Percent", rate)
    write.basic(write.aggregate(holder, "TaxScheme"), "ID", "VAT")


def _line(
    write: _Writer, root: etree._Element, line: Line, number: int, *, credit: bool, currency: str
) -> None:
    holder = write.aggregate(root, "CreditNoteLine" if credit else "InvoiceLine")
    write.basic(holder, "ID", str(number))
    quantity = {"unitCode": line.unit} if line.unit is not None else {}
    write.basic(
        holder, "CreditedQuantity" if credit else "InvoicedQuantity", line.quantity, **quantity
    )
    write.basic(holder, "LineExtensionAmount", line.net_amount, currencyID=currency)
    item = write.aggregate(holder, "Item")
    write.basic(item, "Name", line.name)
    _category(write, item, "ClassifiedTaxCategory", line.vat_category, line.vat_rate)
    if line.unit_price is not None:
        write.basic(
            write.aggregate(holder, "Price"), "PriceAmount", line.unit_price, currencyID=currency
        )


def draft(fields: InvoiceFields) -> bytes:
    """The UBL 2.1 invoice, or credit note, that ``fields`` describe, as UTF-8 XML."""
    credit = fields.type_code == "381"
    namespaces: dict[str | None, str] = {None: CN if credit else UBL, **_NAMESPACES}
    root = etree.Element(
        f"{{{CN if credit else UBL}}}{'CreditNote' if credit else 'Invoice'}", nsmap=namespaces
    )
    write = _Writer(root)
    currency = fields.currency or "RSD"
    money = {"currencyID": currency}

    write.basic(root, "CustomizationID", SPECIFICATION_IDENTIFIER)
    write.basic(root, "ProfileID", PEPPOL_PROFILE)
    write.basic(root, "ID", fields.number)
    write.basic(root, "IssueDate", fields.issue_date)
    if not credit:
        write.basic(root, "DueDate", fields.due_date)
    write.basic(root, "CreditNoteTypeCode" if credit else "InvoiceTypeCode", fields.type_code)
    write.basic(root, "DocumentCurrencyCode", fields.currency)
    write.basic(root, "BuyerReference", fields.buyer_reference)
    period = write.aggregate(root, "InvoicePeriod")
    write.basic(
        period, "DescriptionCode", SUPPLY_DATE if fields.delivery_date is not None else ISSUE_DATE
    )

    status = {True: "VAT", False: "NO-VAT", None: None}[fields.seller_in_vat_register]
    _party(
        write, write.aggregate(root, "AccountingSupplierParty"), fields.seller, vat_status=status
    )
    _party(write, write.aggregate(root, "AccountingCustomerParty"), fields.buyer, vat_status=None)

    if fields.delivery_date is not None:
        write.basic(write.aggregate(root, "Delivery"), "ActualDeliveryDate", fields.delivery_date)

    payment = fields.payment
    if (credit and fields.due_date is not None) or payment.account or payment.reference:
        means = write.aggregate(root, "PaymentMeans")
        write.basic(means, "PaymentMeansCode", CREDIT_TRANSFER)
        if credit:
            write.basic(means, "PaymentDueDate", fields.due_date)
        if payment.reference is not None:
            reference = (
                f"(mod{payment.model}) {payment.reference}"
                if payment.model is not None
                else payment.reference
            )
            write.basic(means, "PaymentID", reference)
        if payment.account is not None:
            write.basic(write.aggregate(means, "PayeeFinancialAccount"), "ID", payment.account)

    totals = fields.totals
    if totals.tax is not None or fields.vat_breakdown:
        tax = write.aggregate(root, "TaxTotal")
        write.basic(tax, "TaxAmount", totals.tax, **money)
        for row in fields.vat_breakdown:
            subtotal = write.aggregate(tax, "TaxSubtotal")
            write.basic(subtotal, "TaxableAmount", row.taxable_amount, **money)
            write.basic(subtotal, "TaxAmount", row.tax_amount, **money)
            _category(write, subtotal, "TaxCategory", row.vat_category, row.vat_rate)

    monetary = write.aggregate(root, "LegalMonetaryTotal")
    write.basic(monetary, "LineExtensionAmount", totals.line_total, **money)
    write.basic(monetary, "TaxExclusiveAmount", totals.tax_exclusive, **money)
    write.basic(monetary, "TaxInclusiveAmount", totals.tax_inclusive, **money)
    write.basic(monetary, "PrepaidAmount", totals.prepaid, **money)
    write.basic(monetary, "PayableAmount", totals.payable, **money)

    for number, line in enumerate(fields.lines, start=1):
        _line(write, root, line, number, credit=credit, currency=currency)

    etree.indent(root, space="  ")
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
