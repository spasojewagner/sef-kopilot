"""UBL 2.1 ``Invoice`` and ``CreditNote`` → :class:`einvoice_core.model.Invoice`.

The mapping follows the EN 16931-3-2 syntax binding for UBL. It reads only the elements the
semantic model knows about and ignores everything else: whether unknown or misplaced elements
are allowed is the XML Schema's question, not the parser's. Values are converted strictly
(no exponents in decimals, no partial dates); a value that cannot be converted raises a
:class:`ParseError` that points at the element.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Final

from lxml import etree

from einvoice_core import model
from einvoice_core.xml import (
    CN,
    NAMESPACES,
    UBL,
    ParseError,
    Source,
    canonical_xpath,
    load_document,
    qualified_name,
)

__all__ = ["build_invoice", "parse_invoice"]

_DECIMAL: Final = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")
_DATE: Final = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:Z|[+-]\d{2}:\d{2})?$")
_INVOICED_OBJECT_TYPE_CODE: Final = "130"
_PROJECT_REFERENCE_TYPE_CODE: Final = "50"
_VAT_SCHEME: Final = "VAT"

_ROOTS: Final[dict[str, model.DocumentType]] = {
    f"{{{UBL}}}Invoice": "Invoice",
    f"{{{CN}}}CreditNote": "CreditNote",
}
_LINE_ELEMENT: Final[dict[model.DocumentType, str]] = {
    "Invoice": "cac:InvoiceLine",
    "CreditNote": "cac:CreditNoteLine",
}
_QUANTITY_ELEMENT: Final[dict[model.DocumentType, str]] = {
    "Invoice": "cbc:InvoicedQuantity",
    "CreditNote": "cbc:CreditedQuantity",
}
_TYPE_CODE_ELEMENT: Final[dict[model.DocumentType, str]] = {
    "Invoice": "cbc:InvoiceTypeCode",
    "CreditNote": "cbc:CreditNoteTypeCode",
}


# ---------------------------------------------------------------------------
# Element access and value conversion
# ---------------------------------------------------------------------------


def _find(parent: etree._Element, path: str) -> etree._Element | None:
    return parent.find(path, NAMESPACES)


def _findall(parent: etree._Element, path: str) -> list[etree._Element]:
    return parent.findall(path, NAMESPACES)


def _text_of(element: etree._Element) -> str | None:
    """Element text with surrounding whitespace removed; ``None`` when there is none."""
    text = (element.text or "").strip()
    return text or None


def _text(parent: etree._Element, path: str) -> str | None:
    element = _find(parent, path)
    return _text_of(element) if element is not None else None


def _texts(parent: etree._Element, path: str) -> tuple[str, ...]:
    return tuple(text for el in _findall(parent, path) if (text := _text_of(el)) is not None)


def _required_text(parent: etree._Element, path: str) -> str:
    text = _text(parent, path)
    if text is None:
        raise ParseError(f"missing required element {path}", xpath=canonical_xpath(parent))
    return text


def _decimal_of(element: etree._Element) -> Decimal:
    text = _text_of(element) or ""
    if not _DECIMAL.match(text):
        raise ParseError(f"not a decimal number: {text!r}", xpath=canonical_xpath(element))
    try:
        return Decimal(text)
    except InvalidOperation as error:  # pragma: no cover - the regex already excludes this
        raise ParseError(
            f"not a decimal number: {text!r}", xpath=canonical_xpath(element)
        ) from error


def _decimal(parent: etree._Element, path: str) -> Decimal | None:
    element = _find(parent, path)
    return _decimal_of(element) if element is not None else None


def _required_decimal(parent: etree._Element, path: str) -> Decimal:
    element = _find(parent, path)
    if element is None:
        raise ParseError(f"missing required element {path}", xpath=canonical_xpath(parent))
    return _decimal_of(element)


def _date_of(element: etree._Element) -> date:
    text = _text_of(element) or ""
    match = _DATE.match(text)
    if match is None:
        raise ParseError(f"not a date (YYYY-MM-DD): {text!r}", xpath=canonical_xpath(element))
    try:
        return date.fromisoformat(match.group(1))
    except ValueError as error:
        raise ParseError(
            f"not a valid calendar date: {text!r}", xpath=canonical_xpath(element)
        ) from error


def _date(parent: etree._Element, path: str) -> date | None:
    element = _find(parent, path)
    return _date_of(element) if element is not None else None


def _required_date(parent: etree._Element, path: str) -> date:
    element = _find(parent, path)
    if element is None:
        raise ParseError(f"missing required element {path}", xpath=canonical_xpath(parent))
    return _date_of(element)


def _bool_of(element: etree._Element) -> bool:
    text = (_text_of(element) or "").lower()
    if text in {"true", "1"}:
        return True
    if text in {"false", "0"}:
        return False
    raise ParseError(f"not a boolean: {text!r}", xpath=canonical_xpath(element))


def _identifier_of(element: etree._Element) -> model.Identifier | None:
    value = _text_of(element)
    if value is None:
        return None
    return model.Identifier(value=value, scheme=element.get("schemeID"))


def _identifier(parent: etree._Element, path: str) -> model.Identifier | None:
    element = _find(parent, path)
    return _identifier_of(element) if element is not None else None


def _currency(parent: etree._Element, path: str) -> str | None:
    element = _find(parent, path)
    return element.get("currencyID") if element is not None else None


def _quantity(parent: etree._Element, path: str) -> model.Quantity | None:
    element = _find(parent, path)
    if element is None:
        return None
    return model.Quantity(value=_decimal_of(element), unit_code=element.get("unitCode"))


# ---------------------------------------------------------------------------
# Business groups
# ---------------------------------------------------------------------------


def _address(element: etree._Element) -> model.Address:
    return model.Address(
        xpath=canonical_xpath(element),
        street_name=_text(element, "cbc:StreetName"),
        additional_street_name=_text(element, "cbc:AdditionalStreetName"),
        address_lines=_texts(element, "cac:AddressLine/cbc:Line"),
        city_name=_text(element, "cbc:CityName"),
        postal_zone=_text(element, "cbc:PostalZone"),
        country_subentity=_text(element, "cbc:CountrySubentity"),
        country_code=_text(element, "cac:Country/cbc:IdentificationCode"),
    )


def _contact(element: etree._Element) -> model.Contact:
    return model.Contact(
        xpath=canonical_xpath(element),
        name=_text(element, "cbc:Name"),
        telephone=_text(element, "cbc:Telephone"),
        email=_text(element, "cbc:ElectronicMail"),
    )


def _tax_scheme_company_ids(party: etree._Element) -> tuple[str | None, str | None]:
    """(VAT identifier, non-VAT tax registration identifier) from the PartyTaxScheme elements."""
    vat_id: str | None = None
    other_id: str | None = None
    for scheme in _findall(party, "cac:PartyTaxScheme"):
        company_id = _text(scheme, "cbc:CompanyID")
        if company_id is None:
            continue
        if _text(scheme, "cac:TaxScheme/cbc:ID") == _VAT_SCHEME:
            vat_id = vat_id or company_id
        else:
            other_id = other_id or company_id
    return vat_id, other_id


def _party(party: etree._Element, group: etree._Element) -> model.Party:
    """Map a ``cac:Party`` (or a party-like element) to the model.

    ``group`` is the element that represents the business group in the UBL binding
    (``cac:AccountingSupplierParty`` for BG-4); its XPath is what rules will point at.
    """
    vat_id, other_id = _tax_scheme_company_ids(party)
    address = _find(party, "cac:PostalAddress")
    contact = _find(party, "cac:Contact")
    return model.Party(
        xpath=canonical_xpath(group),
        name=_text(party, "cac:PartyLegalEntity/cbc:RegistrationName"),
        trading_name=_text(party, "cac:PartyName/cbc:Name"),
        identifiers=tuple(
            ident
            for el in _findall(party, "cac:PartyIdentification/cbc:ID")
            if (ident := _identifier_of(el)) is not None
        ),
        legal_registration_id=_identifier(party, "cac:PartyLegalEntity/cbc:CompanyID"),
        vat_identifier=vat_id,
        tax_registration_identifier=other_id,
        additional_legal_information=_text(party, "cac:PartyLegalEntity/cbc:CompanyLegalForm"),
        electronic_address=_identifier(party, "cbc:EndpointID"),
        address=_address(address) if address is not None else None,
        contact=_contact(contact) if contact is not None else None,
    )


def _party_group(root: etree._Element, path: str) -> model.Party | None:
    """Seller / buyer: ``cac:AccountingSupplierParty/cac:Party`` style groups."""
    group = _find(root, path)
    if group is None:
        return None
    party = _find(group, "cac:Party")
    if party is None:
        raise ParseError("missing required element cac:Party", xpath=canonical_xpath(group))
    return _party(party, group)


def _bare_party(root: etree._Element, path: str) -> model.Party | None:
    """Payee / tax representative: the party element *is* the group."""
    element = _find(root, path)
    return _party(element, element) if element is not None else None


def _delivery(root: etree._Element) -> model.Delivery | None:
    element = _find(root, "cac:Delivery")
    if element is None:
        return None
    address = _find(element, "cac:DeliveryLocation/cac:Address")
    return model.Delivery(
        xpath=canonical_xpath(element),
        deliver_to_name=_text(element, "cac:DeliveryParty/cac:PartyName/cbc:Name"),
        location_id=_identifier(element, "cac:DeliveryLocation/cbc:ID"),
        actual_delivery_date=_date(element, "cbc:ActualDeliveryDate"),
        address=_address(address) if address is not None else None,
    )


def _credit_transfer(element: etree._Element) -> model.CreditTransfer:
    return model.CreditTransfer(
        xpath=canonical_xpath(element),
        account_id=_text(element, "cbc:ID"),
        account_name=_text(element, "cbc:Name"),
        service_provider_id=_text(element, "cac:FinancialInstitutionBranch/cbc:ID"),
    )


def _payment_instructions(element: etree._Element) -> model.PaymentInstructions:
    code_element = _find(element, "cbc:PaymentMeansCode")
    code = _text_of(code_element) if code_element is not None else None
    if code is None:
        raise ParseError(
            "missing required element cbc:PaymentMeansCode", xpath=canonical_xpath(element)
        )
    return model.PaymentInstructions(
        xpath=canonical_xpath(element),
        means_code=code,
        means_text=code_element.get("name") if code_element is not None else None,
        remittance_information=_texts(element, "cbc:PaymentID"),
        due_date=_date(element, "cbc:PaymentDueDate"),
        credit_transfers=tuple(
            _credit_transfer(account) for account in _findall(element, "cac:PayeeFinancialAccount")
        ),
        card_primary_account_number=_text(element, "cac:CardAccount/cbc:PrimaryAccountNumberID"),
        card_holder_name=_text(element, "cac:CardAccount/cbc:HolderName"),
        mandate_reference=_text(element, "cac:PaymentMandate/cbc:ID"),
        debited_account_id=_text(element, "cac:PaymentMandate/cac:PayerFinancialAccount/cbc:ID"),
    )


def _allowance_charge(element: etree._Element) -> model.AllowanceCharge:
    indicator = _find(element, "cbc:ChargeIndicator")
    if indicator is None:
        raise ParseError(
            "missing required element cbc:ChargeIndicator", xpath=canonical_xpath(element)
        )
    return model.AllowanceCharge(
        xpath=canonical_xpath(element),
        is_charge=_bool_of(indicator),
        amount=_required_decimal(element, "cbc:Amount"),
        base_amount=_decimal(element, "cbc:BaseAmount"),
        percentage=_decimal(element, "cbc:MultiplierFactorNumeric"),
        vat_category_code=_text(element, "cac:TaxCategory/cbc:ID"),
        vat_rate=_decimal(element, "cac:TaxCategory/cbc:Percent"),
        reason=_text(element, "cbc:AllowanceChargeReason"),
        reason_code=_text(element, "cbc:AllowanceChargeReasonCode"),
    )


def _vat_breakdown(element: etree._Element) -> model.VatBreakdown:
    return model.VatBreakdown(
        xpath=canonical_xpath(element),
        taxable_amount=_decimal(element, "cbc:TaxableAmount"),
        tax_amount=_required_decimal(element, "cbc:TaxAmount"),
        category_code=_text(element, "cac:TaxCategory/cbc:ID"),
        rate=_decimal(element, "cac:TaxCategory/cbc:Percent"),
        exemption_reason=_text(element, "cac:TaxCategory/cbc:TaxExemptionReason"),
        exemption_reason_code=_text(element, "cac:TaxCategory/cbc:TaxExemptionReasonCode"),
        tax_scheme=_text(element, "cac:TaxCategory/cac:TaxScheme/cbc:ID"),
    )


def _tax_total(element: etree._Element) -> model.TaxTotal:
    return model.TaxTotal(
        xpath=canonical_xpath(element),
        currency=_currency(element, "cbc:TaxAmount"),
        tax_amount=_required_decimal(element, "cbc:TaxAmount"),
        breakdown=tuple(_vat_breakdown(sub) for sub in _findall(element, "cac:TaxSubtotal")),
    )


def _monetary_totals(root: etree._Element) -> model.MonetaryTotals:
    element = _find(root, "cac:LegalMonetaryTotal")
    if element is None:
        raise ParseError(
            "missing required element cac:LegalMonetaryTotal", xpath=canonical_xpath(root)
        )
    return model.MonetaryTotals(
        xpath=canonical_xpath(element),
        currency=_currency(element, "cbc:PayableAmount"),
        line_extension_amount=_decimal(element, "cbc:LineExtensionAmount"),
        allowance_total_amount=_decimal(element, "cbc:AllowanceTotalAmount"),
        charge_total_amount=_decimal(element, "cbc:ChargeTotalAmount"),
        tax_exclusive_amount=_decimal(element, "cbc:TaxExclusiveAmount"),
        tax_inclusive_amount=_decimal(element, "cbc:TaxInclusiveAmount"),
        prepaid_amount=_decimal(element, "cbc:PrepaidAmount"),
        payable_rounding_amount=_decimal(element, "cbc:PayableRoundingAmount"),
        payable_amount=_required_decimal(element, "cbc:PayableAmount"),
    )


def _period(element: etree._Element) -> model.Period:
    return model.Period(
        xpath=canonical_xpath(element),
        start_date=_date(element, "cbc:StartDate"),
        end_date=_date(element, "cbc:EndDate"),
        description_code=_text(element, "cbc:DescriptionCode"),
    )


def _document_reference(element: etree._Element) -> model.DocumentReference:
    id_element = _find(element, "cbc:ID")
    ident = _identifier_of(id_element) if id_element is not None else None
    if ident is None:
        raise ParseError("missing required element cbc:ID", xpath=canonical_xpath(element))
    embedded = _find(element, "cac:Attachment/cbc:EmbeddedDocumentBinaryObject")
    return model.DocumentReference(
        xpath=canonical_xpath(element),
        id=ident,
        issue_date=_date(element, "cbc:IssueDate"),
        document_type_code=_text(element, "cbc:DocumentTypeCode"),
        description=_text(element, "cbc:DocumentDescription"),
        uri=_text(element, "cac:Attachment/cac:ExternalReference/cbc:URI"),
        embedded_mime_code=embedded.get("mimeCode") if embedded is not None else None,
        embedded_filename=embedded.get("filename") if embedded is not None else None,
        embedded_content=_text_of(embedded) if embedded is not None else None,
    )


def _item(element: etree._Element) -> model.Item:
    return model.Item(
        xpath=canonical_xpath(element),
        name=_text(element, "cbc:Name"),
        description=_text(element, "cbc:Description"),
        sellers_identifier=_text(element, "cac:SellersItemIdentification/cbc:ID"),
        buyers_identifier=_text(element, "cac:BuyersItemIdentification/cbc:ID"),
        standard_identifier=_identifier(element, "cac:StandardItemIdentification/cbc:ID"),
        classification_codes=tuple(
            model.ClassificationCode(
                value=value, list_id=code.get("listID"), list_version_id=code.get("listVersionID")
            )
            for code in _findall(element, "cac:CommodityClassification/cbc:ItemClassificationCode")
            if (value := _text_of(code)) is not None
        ),
        origin_country_code=_text(element, "cac:OriginCountry/cbc:IdentificationCode"),
        attributes=tuple(
            model.ItemAttribute(name=name, value=value)
            for prop in _findall(element, "cac:AdditionalItemProperty")
            if (name := _text(prop, "cbc:Name")) is not None
            and (value := _text(prop, "cbc:Value")) is not None
        ),
    )


def _price(element: etree._Element) -> model.Price:
    discount = _find(element, "cac:AllowanceCharge")
    return model.Price(
        xpath=canonical_xpath(element),
        net_price=_required_decimal(element, "cbc:PriceAmount"),
        discount=_decimal(discount, "cbc:Amount") if discount is not None else None,
        gross_price=_decimal(discount, "cbc:BaseAmount") if discount is not None else None,
        base_quantity=_quantity(element, "cbc:BaseQuantity"),
    )


def _line_vat(element: etree._Element) -> model.LineVat:
    return model.LineVat(
        xpath=canonical_xpath(element),
        category_code=_text(element, "cbc:ID"),
        rate=_decimal(element, "cbc:Percent"),
        tax_scheme=_text(element, "cac:TaxScheme/cbc:ID"),
    )


def _line(
    element: etree._Element, position: int, document_type: model.DocumentType
) -> model.InvoiceLine:
    item = _find(element, "cac:Item")
    if item is None:
        raise ParseError("missing required element cac:Item", xpath=canonical_xpath(element))
    object_reference = next(
        (
            ref
            for ref in _findall(element, "cac:DocumentReference")
            if _text(ref, "cbc:DocumentTypeCode") == _INVOICED_OBJECT_TYPE_CODE
        ),
        None,
    )
    period = _find(element, "cac:InvoicePeriod")
    price = _find(element, "cac:Price")
    vat = _find(item, "cac:ClassifiedTaxCategory")
    return model.InvoiceLine(
        xpath=canonical_xpath(element),
        position=position,
        id=_required_text(element, "cbc:ID"),
        note=_text(element, "cbc:Note"),
        object_identifier=(
            _identifier(object_reference, "cbc:ID") if object_reference is not None else None
        ),
        quantity=_quantity(element, _QUANTITY_ELEMENT[document_type]),
        net_amount=_required_decimal(element, "cbc:LineExtensionAmount"),
        order_line_reference=_text(element, "cac:OrderLineReference/cbc:LineID"),
        accounting_cost=_text(element, "cbc:AccountingCost"),
        period=_period(period) if period is not None else None,
        allowances_charges=tuple(
            _allowance_charge(ac) for ac in _findall(element, "cac:AllowanceCharge")
        ),
        price=_price(price) if price is not None else None,
        vat=_line_vat(vat) if vat is not None else None,
        item=_item(item),
    )


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------


def _extension_names(root: etree._Element) -> tuple[str, ...]:
    return tuple(
        qualified_name(child)
        for content in _findall(root, "ext:UBLExtensions/ext:UBLExtension/ext:ExtensionContent")
        for child in content
        if isinstance(child.tag, str)
    )


def _project_reference(root: etree._Element, document_type: model.DocumentType) -> str | None:
    """BT-11: ``cac:ProjectReference`` on invoices.

    UBL 2.1 credit notes have no ``cac:ProjectReference``; the EN 16931 binding carries the
    project reference there as an ``AdditionalDocumentReference`` with type code 50.
    """
    if document_type == "Invoice":
        return _text(root, "cac:ProjectReference/cbc:ID")
    for reference in _findall(root, "cac:AdditionalDocumentReference"):
        if _text(reference, "cbc:DocumentTypeCode") == _PROJECT_REFERENCE_TYPE_CODE:
            return _text(reference, "cbc:ID")
    return None


def _due_date(root: etree._Element) -> date | None:
    """BT-9: ``cbc:DueDate`` on invoices, ``PaymentMeans/cbc:PaymentDueDate`` on credit notes."""
    due = _date(root, "cbc:DueDate")
    return due if due is not None else _date(root, "cac:PaymentMeans/cbc:PaymentDueDate")


def _required_party(root: etree._Element, path: str) -> model.Party:
    party = _party_group(root, path)
    if party is None:
        raise ParseError(f"missing required element {path}", xpath=canonical_xpath(root))
    return party


def build_invoice(root: etree._Element) -> model.Invoice:
    """Build the model from the root element of a parsed UBL document."""
    document_type = _ROOTS.get(root.tag if isinstance(root.tag, str) else "")
    if document_type is None:
        raise ParseError(
            "unsupported document: expected a UBL 2.1 Invoice or CreditNote, "
            f"got {qualified_name(root)}",
            xpath=canonical_xpath(root),
        )
    period = _find(root, "cac:InvoicePeriod")
    lines = _findall(root, _LINE_ELEMENT[document_type])
    if not lines:
        raise ParseError(
            f"missing required element {_LINE_ELEMENT[document_type]}", xpath=canonical_xpath(root)
        )
    return model.Invoice(
        xpath=canonical_xpath(root),
        document_type=document_type,
        specification_id=_text(root, "cbc:CustomizationID"),
        business_process=_text(root, "cbc:ProfileID"),
        id=_required_text(root, "cbc:ID"),
        issue_date=_required_date(root, "cbc:IssueDate"),
        type_code=_text(root, _TYPE_CODE_ELEMENT[document_type]),
        currency=_text(root, "cbc:DocumentCurrencyCode"),
        tax_currency=_text(root, "cbc:TaxCurrencyCode"),
        tax_point_date=_date(root, "cbc:TaxPointDate"),
        due_date=_due_date(root),
        notes=_texts(root, "cbc:Note"),
        buyer_reference=_text(root, "cbc:BuyerReference"),
        accounting_cost=_text(root, "cbc:AccountingCost"),
        payment_terms=_text(root, "cac:PaymentTerms/cbc:Note"),
        period=_period(period) if period is not None else None,
        purchase_order_reference=_text(root, "cac:OrderReference/cbc:ID"),
        sales_order_reference=_text(root, "cac:OrderReference/cbc:SalesOrderID"),
        contract_reference=_text(root, "cac:ContractDocumentReference/cbc:ID"),
        despatch_advice_reference=_text(root, "cac:DespatchDocumentReference/cbc:ID"),
        receiving_advice_reference=_text(root, "cac:ReceiptDocumentReference/cbc:ID"),
        tender_or_lot_reference=_text(root, "cac:OriginatorDocumentReference/cbc:ID"),
        project_reference=_project_reference(root, document_type),
        preceding_invoice_references=tuple(
            _document_reference(ref)
            for ref in _findall(root, "cac:BillingReference/cac:InvoiceDocumentReference")
        ),
        additional_document_references=tuple(
            _document_reference(ref) for ref in _findall(root, "cac:AdditionalDocumentReference")
        ),
        seller=_required_party(root, "cac:AccountingSupplierParty"),
        buyer=_required_party(root, "cac:AccountingCustomerParty"),
        payee=_bare_party(root, "cac:PayeeParty"),
        tax_representative=_bare_party(root, "cac:TaxRepresentativeParty"),
        delivery=_delivery(root),
        payment_instructions=tuple(
            _payment_instructions(means) for means in _findall(root, "cac:PaymentMeans")
        ),
        allowances_charges=tuple(
            _allowance_charge(ac) for ac in _findall(root, "cac:AllowanceCharge")
        ),
        tax_totals=tuple(_tax_total(total) for total in _findall(root, "cac:TaxTotal")),
        totals=_monetary_totals(root),
        lines=tuple(
            _line(element, position, document_type)
            for position, element in enumerate(lines, start=1)
        ),
        extension_names=_extension_names(root),
    )


def parse_invoice(source: Source, *, max_bytes: int | None = None) -> model.Invoice:
    """Load a UBL 2.1 invoice or credit note from bytes, a path or a binary stream.

    This is the one-call entry point; callers that also need the XML tree (for Schematron,
    XPath-addressed violations or patching) use :func:`einvoice_core.xml.load_document`
    followed by :func:`build_invoice`.
    """
    tree = (
        load_document(source) if max_bytes is None else load_document(source, max_bytes=max_bytes)
    )
    return build_invoice(tree.getroot())
