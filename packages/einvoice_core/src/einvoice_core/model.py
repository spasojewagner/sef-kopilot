"""Typed invoice document model.

The model follows the **EN 16931-1 semantic model**, not the UBL syntax: every field names the
business term (``BT-n``) or business group (``BG-n``) it represents, so that validation rules,
explanations and citations can speak the language of the standard regardless of the syntax
the invoice arrived in (UBL today, CII or an extracted PDF later). See ADR-0003.

Design rules:

* Amounts and quantities are :class:`decimal.Decimal`, never ``float``.
* A field is required only when the UBL 2.1 schema itself requires the element; everything
  EN 16931 additionally demands (invoice type code, currency, seller name, ...) is optional
  here and its absence is reported by the business-rule layer as a violation, not by the
  parser as an exception.
* Every business group carries the canonical XPath of the element it was read from, so a
  rule can point at the exact place in the original document.
* Models are strict and frozen: the parser does the type conversion, the rest of the system
  treats a parsed document as an immutable value.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DocumentType = Literal["Invoice", "CreditNote"]


class _Model(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


class Identifier(_Model):
    """An identifier with its optional scheme (``schemeID`` attribute in UBL)."""

    value: str
    scheme: str | None = Field(
        default=None,
        description="Identification scheme, e.g. 0088 or 9948.",
    )


class ClassificationCode(_Model):
    """BT-158 item classification identifier with its list and list version."""

    value: str
    list_id: str | None = Field(default=None, description="Code list identifier (listID).")
    list_version_id: str | None = Field(
        default=None, description="Code list version (listVersionID)."
    )


class Quantity(_Model):
    """A quantity with its unit of measure (UN/ECE Recommendation 20 / 21 code)."""

    value: Decimal
    unit_code: str | None = Field(default=None, description="Unit of measure code (unitCode).")


class Period(_Model):
    """BG-14 invoicing period or BG-26 invoice line period."""

    xpath: str
    start_date: date | None = Field(default=None, description="BT-73 / BT-134 period start date.")
    end_date: date | None = Field(default=None, description="BT-74 / BT-135 period end date.")
    description_code: str | None = Field(
        default=None, description="BT-8 value added tax point date code (UNCL 2005)."
    )


class DocumentReference(_Model):
    """A reference to another document (BT-12, BT-13, BT-16, BT-17, BT-25, BG-24, ...)."""

    xpath: str
    id: Identifier
    issue_date: date | None = Field(default=None, description="BT-26 preceding invoice issue date.")
    document_type_code: str | None = Field(
        default=None, description="UNCL 1001 code; 130 marks an invoiced object identifier (BT-18)."
    )
    description: str | None = Field(
        default=None,
        description="BT-123 supporting document description.",
    )
    uri: str | None = Field(default=None, description="BT-124 external document location.")
    embedded_mime_code: str | None = Field(
        default=None, description="BT-125-1 MIME code of the embedded attachment."
    )
    embedded_filename: str | None = Field(
        default=None, description="BT-125-2 file name of the embedded attachment."
    )
    embedded_content: str | None = Field(
        default=None, description="BT-125 embedded attachment, base64 as found in the document."
    )


# ---------------------------------------------------------------------------
# Parties
# ---------------------------------------------------------------------------


class Address(_Model):
    """BG-5 seller, BG-8 buyer, BG-12 tax representative or BG-15 deliver-to address."""

    xpath: str
    street_name: str | None = Field(default=None, description="BT-35 / BT-50 address line 1.")
    additional_street_name: str | None = Field(
        default=None, description="BT-36 / BT-51 address line 2."
    )
    address_lines: tuple[str, ...] = Field(
        default=(),
        description="BT-162 / BT-163 address line 3.",
    )
    city_name: str | None = Field(default=None, description="BT-37 / BT-52 city.")
    postal_zone: str | None = Field(default=None, description="BT-38 / BT-53 post code.")
    country_subentity: str | None = Field(
        default=None, description="BT-39 / BT-54 country subdivision."
    )
    country_code: str | None = Field(
        default=None,
        description="BT-40 / BT-55 country code (ISO 3166-1).",
    )


class Contact(_Model):
    """BG-6 seller or BG-9 buyer contact."""

    xpath: str
    name: str | None = Field(default=None, description="BT-41 / BT-56 contact point.")
    telephone: str | None = Field(default=None, description="BT-42 / BT-57 telephone number.")
    email: str | None = Field(default=None, description="BT-43 / BT-58 email address.")


class Party(_Model):
    """A trading party: BG-4 seller, BG-7 buyer, BG-10 payee or BG-11 tax representative.

    The same shape serves all four groups; the business-term numbers differ per role and are
    listed in the field descriptions as seller / buyer.
    """

    xpath: str
    name: str | None = Field(
        default=None,
        description="BT-27 / BT-44 registered name (PartyLegalEntity/RegistrationName).",
    )
    trading_name: str | None = Field(
        default=None,
        description="BT-28 / BT-45 trading name (PartyName).",
    )
    identifiers: tuple[Identifier, ...] = Field(
        default=(), description="BT-29 / BT-46 party identifiers (PartyIdentification)."
    )
    legal_registration_id: Identifier | None = Field(
        default=None,
        description="BT-30 / BT-47 legal registration identifier (PartyLegalEntity/CompanyID).",
    )
    vat_identifier: str | None = Field(
        default=None, description="BT-31 / BT-48 VAT identifier (PartyTaxScheme with scheme VAT)."
    )
    tax_registration_identifier: str | None = Field(
        default=None,
        description="BT-32 seller tax registration identifier (PartyTaxScheme, non-VAT scheme).",
    )
    additional_legal_information: str | None = Field(
        default=None, description="BT-33 seller additional legal information (CompanyLegalForm)."
    )
    electronic_address: Identifier | None = Field(
        default=None, description="BT-34 / BT-49 electronic address with its scheme (EndpointID)."
    )
    address: Address | None = Field(default=None, description="BG-5 / BG-8 / BG-12 postal address.")
    contact: Contact | None = Field(default=None, description="BG-6 / BG-9 contact.")


class Delivery(_Model):
    """BG-13 delivery information."""

    xpath: str
    deliver_to_name: str | None = Field(default=None, description="BT-70 deliver to party name.")
    location_id: Identifier | None = Field(
        default=None,
        description="BT-71 deliver to location identifier.",
    )
    actual_delivery_date: date | None = Field(
        default=None,
        description="BT-72 actual delivery date.",
    )
    address: Address | None = Field(default=None, description="BG-15 deliver to address.")


# ---------------------------------------------------------------------------
# Payment
# ---------------------------------------------------------------------------


class CreditTransfer(_Model):
    """BG-17 credit transfer account."""

    xpath: str
    account_id: str | None = Field(
        default=None,
        description="BT-84 payment account identifier (IBAN or local).",
    )
    account_name: str | None = Field(default=None, description="BT-85 payment account name.")
    service_provider_id: str | None = Field(
        default=None, description="BT-86 payment service provider identifier (BIC)."
    )


class PaymentInstructions(_Model):
    """BG-16 payment instructions (one ``cac:PaymentMeans`` element)."""

    xpath: str
    means_code: str = Field(description="BT-81 payment means type code (UNCL 4461).")
    means_text: str | None = Field(default=None, description="BT-82 payment means text.")
    remittance_information: tuple[str, ...] = Field(
        default=(), description="BT-83 remittance information (PaymentID)."
    )
    due_date: date | None = Field(
        default=None,
        description="BT-9 payment due date when carried on PaymentMeans (credit notes).",
    )
    credit_transfers: tuple[CreditTransfer, ...] = Field(
        default=(),
        description="BG-17 credit transfer accounts.",
    )
    card_primary_account_number: str | None = Field(
        default=None, description="BT-87 payment card primary account number (masked)."
    )
    card_holder_name: str | None = Field(
        default=None,
        description="BT-88 payment card holder name.",
    )
    mandate_reference: str | None = Field(
        default=None,
        description="BT-89 direct debit mandate reference.",
    )
    debited_account_id: str | None = Field(
        default=None,
        description="BT-91 debited account identifier.",
    )


# ---------------------------------------------------------------------------
# Allowances, charges and tax
# ---------------------------------------------------------------------------


class AllowanceCharge(_Model):
    """BG-20 / BG-21 document level, or BG-27 / BG-28 line level, allowance or charge."""

    xpath: str
    is_charge: bool = Field(
        description="True for a charge (BG-21 / BG-28), false for an allowance.",
    )
    amount: Decimal = Field(description="BT-92 / BT-99 / BT-136 / BT-141 amount.")
    base_amount: Decimal | None = Field(
        default=None,
        description="BT-93 / BT-100 / BT-137 / BT-142 base amount.",
    )
    percentage: Decimal | None = Field(
        default=None,
        description="BT-94 / BT-101 / BT-138 / BT-143 percentage (MultiplierFactorNumeric).",
    )
    vat_category_code: str | None = Field(
        default=None, description="BT-95 / BT-102 VAT category code (document level only)."
    )
    vat_rate: Decimal | None = Field(
        default=None,
        description="BT-96 / BT-103 VAT rate (document level only).",
    )
    reason: str | None = Field(
        default=None,
        description="BT-97 / BT-104 / BT-139 / BT-144 reason text.",
    )
    reason_code: str | None = Field(
        default=None,
        description="BT-98 / BT-105 / BT-140 / BT-145 reason code.",
    )


class VatBreakdown(_Model):
    """BG-23 VAT breakdown (one ``cac:TaxSubtotal``)."""

    xpath: str
    taxable_amount: Decimal | None = Field(
        default=None,
        description="BT-116 VAT category taxable amount.",
    )
    tax_amount: Decimal = Field(description="BT-117 VAT category tax amount.")
    category_code: str | None = Field(
        default=None,
        description="BT-118 VAT category code (UNCL 5305).",
    )
    rate: Decimal | None = Field(default=None, description="BT-119 VAT category rate.")
    exemption_reason: str | None = Field(
        default=None,
        description="BT-120 VAT exemption reason text.",
    )
    exemption_reason_code: str | None = Field(
        default=None,
        description="BT-121 VAT exemption reason code.",
    )
    tax_scheme: str | None = Field(default=None, description="Tax scheme identifier, normally VAT.")


class TaxTotal(_Model):
    """One ``cac:TaxTotal``: the total VAT amount in one currency with its breakdown.

    An invoice carries one tax total in the document currency (BT-110 with BG-23) and, when
    VAT is accounted in another currency, a second one holding BT-111 only.
    """

    xpath: str
    currency: str | None = Field(default=None, description="Currency of the amounts (currencyID).")
    tax_amount: Decimal = Field(
        description="BT-110 (document currency) or BT-111 (accounting currency).",
    )
    breakdown: tuple[VatBreakdown, ...] = Field(
        default=(),
        description="BG-23 VAT breakdown entries.",
    )


class MonetaryTotals(_Model):
    """BG-22 document totals (``cac:LegalMonetaryTotal``)."""

    xpath: str
    currency: str | None = Field(default=None, description="Currency of the amounts (currencyID).")
    line_extension_amount: Decimal | None = Field(
        default=None,
        description="BT-106 sum of invoice line net amounts.",
    )
    allowance_total_amount: Decimal | None = Field(
        default=None,
        description="BT-107 sum of allowances on document level.",
    )
    charge_total_amount: Decimal | None = Field(
        default=None,
        description="BT-108 sum of charges on document level.",
    )
    tax_exclusive_amount: Decimal | None = Field(
        default=None,
        description="BT-109 invoice total amount without VAT.",
    )
    tax_inclusive_amount: Decimal | None = Field(
        default=None,
        description="BT-112 invoice total amount with VAT.",
    )
    prepaid_amount: Decimal | None = Field(default=None, description="BT-113 paid amount.")
    payable_rounding_amount: Decimal | None = Field(
        default=None,
        description="BT-114 rounding amount.",
    )
    payable_amount: Decimal = Field(description="BT-115 amount due for payment.")


# ---------------------------------------------------------------------------
# Lines
# ---------------------------------------------------------------------------


class ItemAttribute(_Model):
    """BG-32 item attribute."""

    name: str = Field(description="BT-160 item attribute name.")
    value: str = Field(description="BT-161 item attribute value.")


class Item(_Model):
    """BG-31 item information."""

    xpath: str
    name: str | None = Field(default=None, description="BT-153 item name.")
    description: str | None = Field(default=None, description="BT-154 item description.")
    sellers_identifier: str | None = Field(
        default=None,
        description="BT-155 item seller's identifier.",
    )
    buyers_identifier: str | None = Field(
        default=None,
        description="BT-156 item buyer's identifier.",
    )
    standard_identifier: Identifier | None = Field(
        default=None,
        description="BT-157 item standard identifier.",
    )
    classification_codes: tuple[ClassificationCode, ...] = Field(
        default=(), description="BT-158 item classification identifiers."
    )
    origin_country_code: str | None = Field(
        default=None,
        description="BT-159 item country of origin.",
    )
    attributes: tuple[ItemAttribute, ...] = Field(default=(), description="BG-32 item attributes.")


class Price(_Model):
    """BG-29 price details."""

    xpath: str
    net_price: Decimal = Field(description="BT-146 item net price (PriceAmount).")
    discount: Decimal | None = Field(default=None, description="BT-147 item price discount.")
    gross_price: Decimal | None = Field(default=None, description="BT-148 item gross price.")
    base_quantity: Quantity | None = Field(
        default=None,
        description="BT-149 / BT-150 item price base quantity and unit.",
    )


class LineVat(_Model):
    """BG-30 line VAT information (``cac:ClassifiedTaxCategory``)."""

    xpath: str
    category_code: str | None = Field(
        default=None,
        description="BT-151 invoiced item VAT category code.",
    )
    rate: Decimal | None = Field(default=None, description="BT-152 invoiced item VAT rate.")
    tax_scheme: str | None = Field(default=None, description="Tax scheme identifier, normally VAT.")


class InvoiceLine(_Model):
    """BG-25 invoice line (``cac:InvoiceLine`` or ``cac:CreditNoteLine``)."""

    xpath: str
    position: int = Field(description="1-based position of the line in the document.")
    id: str = Field(description="BT-126 invoice line identifier.")
    note: str | None = Field(default=None, description="BT-127 invoice line note.")
    object_identifier: Identifier | None = Field(
        default=None,
        description="BT-128 invoice line object identifier.",
    )
    quantity: Quantity | None = Field(
        default=None,
        description="BT-129 invoiced quantity with BT-130 unit.",
    )
    net_amount: Decimal = Field(description="BT-131 invoice line net amount (LineExtensionAmount).")
    order_line_reference: str | None = Field(
        default=None,
        description="BT-132 referenced purchase order line.",
    )
    accounting_cost: str | None = Field(
        default=None,
        description="BT-133 invoice line buyer accounting reference.",
    )
    period: Period | None = Field(default=None, description="BG-26 invoice line period.")
    allowances_charges: tuple[AllowanceCharge, ...] = Field(
        default=(), description="BG-27 line allowances and BG-28 line charges."
    )
    price: Price | None = Field(default=None, description="BG-29 price details.")
    vat: LineVat | None = Field(default=None, description="BG-30 line VAT information.")
    item: Item = Field(description="BG-31 item information.")

    @property
    def allowances(self) -> tuple[AllowanceCharge, ...]:
        return tuple(ac for ac in self.allowances_charges if not ac.is_charge)

    @property
    def charges(self) -> tuple[AllowanceCharge, ...]:
        return tuple(ac for ac in self.allowances_charges if ac.is_charge)


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------


class Invoice(_Model):
    """An invoice or credit note, as the EN 16931 semantic model sees it."""

    xpath: str
    document_type: DocumentType = Field(description="UBL document type the model was read from.")
    specification_id: str | None = Field(
        default=None,
        description="BT-24 specification identifier (CustomizationID).",
    )
    business_process: str | None = Field(
        default=None,
        description="BT-23 business process type (ProfileID).",
    )
    id: str = Field(description="BT-1 invoice number.")
    issue_date: date = Field(description="BT-2 invoice issue date.")
    type_code: str | None = Field(default=None, description="BT-3 invoice type code (UNCL 1001).")
    currency: str | None = Field(default=None, description="BT-5 invoice currency code (ISO 4217).")
    tax_currency: str | None = Field(default=None, description="BT-6 VAT accounting currency code.")
    tax_point_date: date | None = Field(
        default=None,
        description="BT-7 value added tax point date.",
    )
    due_date: date | None = Field(default=None, description="BT-9 payment due date.")
    notes: tuple[str, ...] = Field(default=(), description="BT-22 invoice notes.")
    buyer_reference: str | None = Field(default=None, description="BT-10 buyer reference.")
    accounting_cost: str | None = Field(
        default=None,
        description="BT-19 buyer accounting reference.",
    )
    payment_terms: str | None = Field(default=None, description="BT-20 payment terms.")
    period: Period | None = Field(default=None, description="BG-14 invoicing period, incl. BT-8.")
    purchase_order_reference: str | None = Field(
        default=None,
        description="BT-13 purchase order reference.",
    )
    sales_order_reference: str | None = Field(
        default=None,
        description="BT-14 sales order reference.",
    )
    contract_reference: str | None = Field(default=None, description="BT-12 contract reference.")
    despatch_advice_reference: str | None = Field(
        default=None,
        description="BT-16 despatch advice reference.",
    )
    receiving_advice_reference: str | None = Field(
        default=None,
        description="BT-15 receiving advice reference.",
    )
    tender_or_lot_reference: str | None = Field(
        default=None,
        description="BT-17 tender or lot reference.",
    )
    project_reference: str | None = Field(
        default=None,
        description=(
            "BT-11 project reference: ProjectReference on invoices; on credit notes, which have "
            "no ProjectReference in UBL 2.1, an AdditionalDocumentReference with type code 50."
        ),
    )
    preceding_invoice_references: tuple[DocumentReference, ...] = Field(
        default=(), description="BG-3 preceding invoice references (BT-25, BT-26)."
    )
    additional_document_references: tuple[DocumentReference, ...] = Field(
        default=(),
        description=(
            "Every AdditionalDocumentReference in document order: BG-24 additional supporting "
            "documents, BT-18 invoiced object identifier (type code 130) and, on credit notes, "
            "BT-11 project reference (type code 50)."
        ),
    )
    seller: Party = Field(description="BG-4 seller.")
    buyer: Party = Field(description="BG-7 buyer.")
    payee: Party | None = Field(default=None, description="BG-10 payee.")
    tax_representative: Party | None = Field(
        default=None,
        description="BG-11 seller tax representative party.",
    )
    delivery: Delivery | None = Field(default=None, description="BG-13 delivery information.")
    payment_instructions: tuple[PaymentInstructions, ...] = Field(
        default=(), description="BG-16 payment instructions (one per PaymentMeans element)."
    )
    allowances_charges: tuple[AllowanceCharge, ...] = Field(
        default=(), description="BG-20 document level allowances and BG-21 charges."
    )
    tax_totals: tuple[TaxTotal, ...] = Field(
        default=(),
        description="BT-110 / BT-111 with the BG-23 breakdown.",
    )
    totals: MonetaryTotals = Field(description="BG-22 document totals.")
    lines: tuple[InvoiceLine, ...] = Field(description="BG-25 invoice lines.")
    extension_names: tuple[str, ...] = Field(
        default=(), description="Qualified names of the children of ext:UBLExtensions, if any."
    )

    @property
    def allowances(self) -> tuple[AllowanceCharge, ...]:
        return tuple(ac for ac in self.allowances_charges if not ac.is_charge)

    @property
    def charges(self) -> tuple[AllowanceCharge, ...]:
        return tuple(ac for ac in self.allowances_charges if ac.is_charge)

    @property
    def vat_breakdown(self) -> tuple[VatBreakdown, ...]:
        """BG-23 entries of the tax total expressed in the document currency (BT-110)."""
        total = self.document_currency_tax_total
        return total.breakdown if total is not None else ()

    @property
    def document_currency_tax_total(self) -> TaxTotal | None:
        """The ``cac:TaxTotal`` that carries BT-110 and the VAT breakdown.

        When the currency of a tax total is not stated it is taken to be the document currency,
        which is how the UBL binding of EN 16931 reads it.
        """
        for total in self.tax_totals:
            if total.currency is None or total.currency == self.currency:
                return total
        return None
