"""The fields of an invoice as a document prints them: what the reading model fills in from a
PDF or a picture, and what a person confirms before a UBL invoice is made of them (ADR-0062).

The fields are the business terms of EN 16931 that a Serbian invoice prints and SEF needs, in
the plain form a printed invoice gives them: names, the PIB and the registration number, dates,
amounts. They are not UBL: :mod:`sef_api.extraction.draft` writes the UBL from them, in code.

Every value is text, or null where the document does not show it: the model writes what it
reads, and invents nothing. A character XML cannot hold (a control character, as PDFium marks a
hyphen at a line break) is dropped from a value, so that every value can be written into an
invoice. A value must have the form its description gives (a date as
``2026-10-05``, an amount as ``14400.00``), which the models check: an answer that breaks one
is sent back to the model with what is wrong, as the explainer's and the repairer's are.

:data:`SCHEMA` is the answer's JSON schema, made from the models for structured outputs in
strict mode: every key is required, every value may be null, nothing else is allowed.
:func:`fields_of` reads the same fields from an invoice the validator parsed, for the tests
and the evaluations, whose documents are made from known invoices.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Final, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from einvoice_core import model
from einvoice_core.srb.vat import CATEGORIES

__all__ = [
    "MAX_LINES",
    "NOT_IN_XML",
    "SCHEMA",
    "InvoiceFields",
    "Line",
    "Party",
    "Payment",
    "Totals",
    "VatSubtotal",
    "fields_of",
]

#: The most lines a document may have read from it: more than an invoice of three pages holds.
MAX_LINES: Final = 200
#: The longest value of a field, which no name, address or identifier needs to pass.
MAX_TEXT: Final = 500

#: What XML 1.0 cannot hold (its production ``Char``): control characters other than the tab
#: and the line ends, U+FFFE, U+FFFF and lone surrogates.
NOT_IN_XML: Final = re.compile("[^\t\n\r\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")

_AMOUNT = re.compile(r"-?[0-9]+(\.[0-9]+)?")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = " ".join(NOT_IN_XML.sub("", value).split())
    if len(stripped) > MAX_TEXT:
        raise ValueError(f"at most {MAX_TEXT} characters")
    return stripped or None


def _amount(value: str | None) -> str | None:
    value = _text(value)
    if value is not None and _AMOUNT.fullmatch(value) is None:
        raise ValueError(
            "write a number as digits with a decimal point, 1234.56, without thousands separators "
            "or a currency"
        )
    return value


def _date(value: str | None) -> str | None:
    value = _text(value)
    if value is None:
        return None
    try:
        if _DATE.fullmatch(value) is None:
            raise ValueError
        date.fromisoformat(value)
    except ValueError:
        raise ValueError("write a date as YYYY-MM-DD, 2026-10-05") from None
    return value


def _code(pattern: str, form: str) -> Any:
    compiled = re.compile(pattern)

    def check(value: str | None) -> str | None:
        value = _text(value)
        if value is not None:
            value = value.upper()
            if compiled.fullmatch(value) is None:
                raise ValueError(f"write {form}")
        return value

    return check


Text = Annotated[str | None, AfterValidator(_text)]
Amount = Annotated[str | None, AfterValidator(_amount)]
Day = Annotated[str | None, AfterValidator(_date)]
Currency = Annotated[str | None, AfterValidator(_code(r"[A-Z]{3}", "an ISO 4217 code, RSD"))]
Country = Annotated[str | None, AfterValidator(_code(r"[A-Z]{2}", "an ISO 3166 code, RS"))]
Unit = Annotated[
    str | None, AfterValidator(_code(r"[A-Z0-9]{2,3}", "a UN/ECE Recommendation 20 code, H87"))
]
TypeCode = Literal["380", "381", "383", "386"]
Category = Literal["S", "Z", "E", "AE", "R", "O", "OE", "SS", "N"]


class _Fields(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Party(_Fields):
    """A party to the invoice, as its header or its footer prints it."""

    name: Text = Field(
        default=None,
        description="Its name as printed, with its legal form (d.o.o., a.d., preduzetnik).",
    )
    tax_id: Text = Field(
        default=None,
        description="Its PIB, the tax identification number: nine digits, without RS before them.",
    )
    company_id: Text = Field(
        default=None, description="Its matični broj (MB), the registration number: eight digits."
    )
    street: Text = Field(default=None, description="Its street and number.")
    city: Text = Field(default=None, description="Its city or place.")
    postal_code: Text = Field(default=None, description="Its postal code: five digits in Serbia.")
    country: Country = Field(
        default=None,
        description="Its country as an ISO 3166-1 alpha-2 code: RS for Serbia, also when the "
        "address names none.",
    )
    email: Text = Field(default=None, description="Its email address, if printed.")


class Line(_Fields):
    """A line of the invoice's table of goods and services."""

    name: Text = Field(default=None, description="What was sold or done, as the line names it.")
    quantity: Amount = Field(default=None, description="The quantity, a number: 8.")
    unit: Unit = Field(
        default=None,
        description="The unit as a UN/ECE Recommendation 20 code: H87 for a piece (kom), HUR "
        "for an hour (sat), DAY for a day, KGM for a kilogram, LTR for a litre, MTR for a metre, "
        "C62 when no unit is printed.",
    )
    unit_price: Amount = Field(
        default=None, description="The price of one unit without VAT, a number: 1500.00."
    )
    net_amount: Amount = Field(
        default=None,
        description="The line's amount without VAT, as printed (osnovica): 12000.00.",
    )
    vat_category: Category | None = Field(
        default=None,
        description="The VAT category: S where VAT is charged at 20 or 10 percent; AE where "
        "the buyer owes it (reverse charge); Z, E, R, O, OE, SS or N where the line names an "
        "exemption or VAT does not apply.",
    )
    vat_rate: Amount = Field(
        default=None, description="The VAT rate in percent, a number: 20, 10 or 0."
    )


class VatSubtotal(_Fields):
    """A row of the VAT recapitulation: the amounts of one category and rate."""

    vat_category: Category | None = Field(
        default=None, description="The VAT category, as for a line: S, AE, Z, E, R, O, OE, SS, N."
    )
    vat_rate: Amount = Field(default=None, description="The VAT rate in percent: 20, 10 or 0.")
    taxable_amount: Amount = Field(
        default=None, description="The amount the VAT is charged on (osnovica): 12000.00."
    )
    tax_amount: Amount = Field(default=None, description="The VAT itself (iznos PDV): 2400.00.")


class Totals(_Fields):
    """The invoice's totals, as its foot prints them."""

    line_total: Amount = Field(
        default=None, description="The sum of the lines' amounts without VAT."
    )
    tax_exclusive: Amount = Field(
        default=None, description="The total without VAT (ukupna osnovica)."
    )
    tax: Amount = Field(default=None, description="The total VAT (ukupan PDV).")
    tax_inclusive: Amount = Field(
        default=None, description="The total with VAT (ukupno sa PDV-om)."
    )
    prepaid: Amount = Field(
        default=None, description="What was paid in advance (avans), if printed."
    )
    payable: Amount = Field(
        default=None, description="The amount due for payment (za uplatu, za plaćanje)."
    )


class Payment(_Fields):
    """How the invoice is to be paid."""

    account: Text = Field(
        default=None,
        description="The seller's bank account (tekući račun) as printed: 160-0000000123456-78.",
    )
    model: Text = Field(
        default=None, description="The payment model (model plaćanja), two digits: 97."
    )
    reference: Text = Field(
        default=None,
        description="The payment reference (poziv na broj), without the model: 12-345678-00123.",
    )


class InvoiceFields(_Fields):
    """An invoice's fields as a document prints them; null where it does not show one."""

    type_code: TypeCode | None = Field(
        default=None,
        description="What the document is: 380 an invoice (račun, faktura), 386 an advance "
        "invoice (avansni račun), 381 a credit note (knjižno odobrenje), 383 a debit note "
        "(knjižno zaduženje).",
    )
    number: Text = Field(default=None, description="The invoice's number (broj računa).")
    issue_date: Day = Field(default=None, description="The date of issue (datum izdavanja).")
    due_date: Day = Field(default=None, description="The payment due date (rok plaćanja, valuta).")
    delivery_date: Day = Field(
        default=None, description="The date of supply (datum prometa), if printed."
    )
    currency: Currency = Field(
        default=None, description="The currency of the amounts as an ISO 4217 code: RSD, EUR."
    )
    buyer_reference: Text = Field(
        default=None,
        description="The buyer's reference or order number (broj narudžbenice), if printed.",
    )
    seller: Party = Field(default_factory=Party, description="Who issues the invoice.")
    seller_in_vat_register: bool | None = Field(
        default=None,
        description="Whether the seller is in the VAT register: true where the invoice charges "
        "VAT or says so (obveznik PDV-a), false where it says it is not (nije u sistemu PDV-a).",
    )
    buyer: Party = Field(default_factory=Party, description="Who is invoiced.")
    lines: list[Line] = Field(
        default_factory=list,
        max_length=MAX_LINES,
        description="The lines, in the order printed.",
    )
    vat_breakdown: list[VatSubtotal] = Field(
        default_factory=list, description="The VAT recapitulation, one row a category and rate."
    )
    totals: Totals = Field(default_factory=Totals, description="The totals.")
    payment: Payment = Field(default_factory=Payment, description="How to pay.")


def _strict(node: Any, definitions: dict[str, Any]) -> Any:
    """``node`` of a model's JSON schema as structured outputs take it in strict mode."""
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        return _strict(definitions[node["$ref"].rsplit("/", 1)[1]], definitions)
    if "anyOf" in node:
        options = [option for option in node["anyOf"] if option != {"type": "null"}]
        if len(options) != 1:  # pragma: no cover - the fields are a value or null
            raise ValueError("a field is a value or null")
        made = _strict(options[0], definitions)
        made["type"] = [made["type"], "null"]
        if "enum" in made:
            made["enum"] = [*made["enum"], None]
        if "description" in node:
            made["description"] = node["description"]
        return made
    made = {key: node[key] for key in ("type", "description", "enum") if key in node}
    if node.get("type") == "object":
        properties = node["properties"]
        made["properties"] = {
            name: _strict(value, definitions) for name, value in properties.items()
        }
        made["required"] = list(properties)
        made["additionalProperties"] = False
    if node.get("type") == "array":
        made["items"] = _strict(node["items"], definitions)
    return made


def _schema() -> dict[str, Any]:
    full = InvoiceFields.model_json_schema()
    made: dict[str, Any] = _strict(full, full.get("$defs", {}))
    made.pop("description", None)
    return made


#: The answer's JSON schema, for structured outputs in strict mode.
SCHEMA: Final[dict[str, Any]] = _schema()


def _plain(number: Decimal | None) -> str | None:
    """A number as the fields write it, without an exponent."""
    return None if number is None else format(number, "f")


def _party(party: model.Party) -> Party:
    address = party.address
    tax_id = party.vat_identifier
    if tax_id is not None and tax_id.upper().startswith("RS"):
        tax_id = tax_id[2:]
    return Party(
        name=party.name or party.trading_name,
        tax_id=tax_id,
        company_id=party.legal_registration_id.value if party.legal_registration_id else None,
        street=address.street_name if address else None,
        city=address.city_name if address else None,
        postal_code=address.postal_zone if address else None,
        country=address.country_code if address else None,
        email=party.contact.email if party.contact else None,
    )


def fields_of(invoice: model.Invoice) -> InvoiceFields:
    """The fields a document made from ``invoice`` prints: what reading it should give."""
    lines = [
        Line(
            name=line.item.name,
            quantity=_plain(line.quantity.value) if line.quantity else None,
            unit=line.quantity.unit_code if line.quantity else None,
            unit_price=_plain(line.price.net_price) if line.price else None,
            net_amount=_plain(line.net_amount),
            vat_category=_category(line.vat.category_code if line.vat else None),
            vat_rate=_plain(line.vat.rate) if line.vat else None,
        )
        for line in invoice.lines
    ]
    breakdown = [
        VatSubtotal(
            vat_category=_category(subtotal.category_code),
            vat_rate=_plain(subtotal.rate),
            taxable_amount=_plain(subtotal.taxable_amount),
            tax_amount=_plain(subtotal.tax_amount),
        )
        for total in invoice.tax_totals[:1]
        for subtotal in total.breakdown
    ]
    totals = invoice.totals
    payment = invoice.payment_instructions[0] if invoice.payment_instructions else None
    account = (
        payment.credit_transfers[0].account_id if payment and payment.credit_transfers else None
    )
    model_number, reference = _remittance(
        payment.remittance_information[0] if payment and payment.remittance_information else None
    )
    return InvoiceFields(
        type_code=_type_code(invoice.type_code),
        number=invoice.id,
        issue_date=invoice.issue_date.isoformat(),
        due_date=invoice.due_date.isoformat() if invoice.due_date else None,
        delivery_date=(
            invoice.delivery.actual_delivery_date.isoformat()
            if invoice.delivery and invoice.delivery.actual_delivery_date
            else None
        ),
        currency=invoice.currency,
        buyer_reference=invoice.buyer_reference,
        seller=_party(invoice.seller),
        seller_in_vat_register=_registered(invoice.seller.tax_registration_identifier),
        buyer=_party(invoice.buyer),
        lines=lines,
        vat_breakdown=breakdown,
        totals=Totals(
            line_total=_plain(totals.line_extension_amount),
            tax_exclusive=_plain(totals.tax_exclusive_amount),
            tax=_plain(invoice.tax_totals[0].tax_amount) if invoice.tax_totals else None,
            tax_inclusive=_plain(totals.tax_inclusive_amount),
            prepaid=_plain(totals.prepaid_amount),
            payable=_plain(totals.payable_amount),
        ),
        payment=Payment(account=account, model=model_number, reference=reference),
    )


def _registered(status: str | None) -> bool | None:
    return {"VAT": True, "NO-VAT": False}.get(status or "")


def _type_code(code: str | None) -> TypeCode | None:
    return code if code in ("380", "381", "383", "386") else None  # type: ignore[return-value]


def _category(code: str | None) -> Category | None:
    return code if code in CATEGORIES else None  # type: ignore[return-value]


_REMITTANCE = re.compile(r"\(mod([0-9]{2})\) (.+)", re.DOTALL)


def _remittance(text: str | None) -> tuple[str | None, str | None]:
    """The payment model and the reference of remittance information written as SRB-019
    prescribes, ``(mod97) 12-345``; the whole text as the reference otherwise."""
    if text is None:
        return None, None
    written = _REMITTANCE.fullmatch(text.strip())
    if written is None:
        return None, text.strip()
    return written.group(1), written.group(2).strip()
