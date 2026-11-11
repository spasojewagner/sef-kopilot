"""The fields of an invoice as a document prints them: the forms their values must have, the
schema the reading model answers in strict mode, and the fields of a known invoice."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from einvoice_core.ubl import parse_invoice
from sef_api.extraction.draft import draft
from sef_api.extraction.fields import (
    MAX_LINES,
    SCHEMA,
    InvoiceFields,
    Line,
    Party,
    Payment,
    Totals,
    VatSubtotal,
    fields_of,
)

SYNTHETIC = Path(__file__).resolve().parents[3] / "fixtures" / "invoices" / "synthetic"


def objects(node: Any) -> list[dict[str, Any]]:
    """Every object of a JSON schema, nested ones included."""
    if not isinstance(node, dict):
        return []
    found = [node] if node.get("type") == "object" else []
    for value in node.get("properties", {}).values():
        found += objects(value)
    if "items" in node:
        found += objects(node["items"])
    return found


def test_the_schema_is_strict_every_key_required_and_nothing_more() -> None:
    every = objects(SCHEMA)
    assert len(every) == 7  # the invoice, two parties, a line, a VAT row, the totals, payment
    for each in every:
        assert each["required"] == list(each["properties"])
        assert each["additionalProperties"] is False
        assert set(each) <= {
            "type",
            "properties",
            "required",
            "additionalProperties",
            "description",
        }


def test_the_schema_names_every_field_of_the_models_and_lets_each_be_null() -> None:
    models: dict[str, type[BaseModel]] = {
        "": InvoiceFields,
        "seller": Party,
        "buyer": Party,
        "lines": Line,
        "vat_breakdown": VatSubtotal,
        "totals": Totals,
        "payment": Payment,
    }
    for name, fields in models.items():
        node = SCHEMA if not name else SCHEMA["properties"][name]
        node = node.get("items", node)
        assert list(node["properties"]) == list(fields.model_fields)
    nullable = [
        value
        for each in objects(SCHEMA)
        for value in each["properties"].values()
        if value["type"] not in ("object", "array")
    ]
    assert len(nullable) > 40
    assert all("null" in value["type"] and value["description"] for value in nullable)
    assert SCHEMA["properties"]["type_code"]["enum"] == ["380", "381", "383", "386", None]
    category = SCHEMA["properties"]["lines"]["items"]["properties"]["vat_category"]
    assert category["enum"] == ["S", "Z", "E", "AE", "R", "O", "OE", "SS", "N", None]
    assert "$defs" not in str(SCHEMA)


def test_an_empty_answer_is_an_invoice_with_nothing_read() -> None:
    nothing = InvoiceFields.model_validate_json("{}")

    assert nothing.number is None
    assert nothing.seller == Party()
    assert nothing.lines == []


def test_values_are_tidied_and_codes_written_in_capitals() -> None:
    fields = InvoiceFields(
        number="  RF-2026-000123 ",
        currency="rsd",
        seller=Party(name="Primer  Softver\n d.o.o.", country="rs", tax_id=""),
        lines=[Line(quantity="8", unit="hur", unit_price="1500.00", vat_rate="20")],
    )

    assert fields.number == "RF-2026-000123"
    assert fields.currency == "RSD"
    assert fields.seller.name == "Primer Softver d.o.o."
    assert fields.seller.country == "RS"
    assert fields.seller.tax_id is None
    assert fields.lines[0].unit == "HUR"


def test_a_character_xml_cannot_hold_is_dropped_so_every_value_can_be_written() -> None:
    """A model copies what a PDF's text holds: PDFium marks a hyphen at a line break with a
    control character, which no XML document may hold."""
    fields = InvoiceFields.model_validate_json(
        '{"number": "RF\\u0000-1", "buyer_reference": "\\ufffe", "seller": '
        '{"name": "Primer\\u0002 Softver\\u0007 d.o.o.", "street": "Ulica\\u0085 Primera 1"}}'
    )

    assert fields.number == "RF-1"
    # A value of nothing but such characters is a value not read.
    assert fields.buyer_reference is None
    assert fields.seller.name == "Primer Softver d.o.o."
    # A character XML holds, a line's end in Unicode's other form, is whitespace as any.
    assert fields.seller.street == "Ulica Primera 1"
    assert b"<cbc:Name>Primer Softver d.o.o.</cbc:Name>" in draft(fields)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("issue_date", "05.10.2026.", "write a date as YYYY-MM-DD"),
        ("issue_date", "2026-02-30", "write a date as YYYY-MM-DD"),
        ("currency", "dinar", "write an ISO 4217 code"),
        ("type_code", "388", "Input should be '380', '381', '383' or '386'"),
        ("number", "x" * 501, "at most 500 characters"),
    ],
)
def test_a_value_of_the_wrong_form_says_which_form(field: str, value: str, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        InvoiceFields.model_validate({field: value})


@pytest.mark.parametrize("amount", ["12.000,00", "12,000.00", "14400 RSD", "1e3", ""])
def test_an_amount_is_digits_and_a_decimal_point(amount: str) -> None:
    if not amount:
        assert Totals(payable=amount).payable is None
        return
    with pytest.raises(ValidationError, match="digits with a decimal point"):
        Totals(payable=amount)


def test_no_more_lines_than_an_invoice_of_three_pages_holds() -> None:
    with pytest.raises(ValidationError, match=f"at most {MAX_LINES} items"):
        InvoiceFields(lines=[Line()] * (MAX_LINES + 1))


def test_a_field_not_in_the_schema_is_refused() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        InvoiceFields.model_validate({"iban": "RS35"})


def test_the_fields_of_a_known_invoice_are_what_its_document_prints() -> None:
    fields = fields_of(parse_invoice(SYNTHETIC / "srb-minimal-invoice.xml"))

    assert fields == InvoiceFields(
        type_code="380",
        number="RF-2026-000123",
        issue_date="2026-10-05",
        due_date="2026-10-20",
        delivery_date="2026-10-05",
        currency="RSD",
        buyer_reference="NAB-77",
        seller=Party(
            name="Primer Softver d.o.o.",
            tax_id="100000024",
            company_id="20000006",
            street="Ulica Primera 1",
            city="Čačak",
            postal_code="32000",
            country="RS",
            email="fakture@primer-softver.example",
        ),
        seller_in_vat_register=True,
        buyer=Party(
            name="Ogledni Kupac d.o.o.",
            tax_id="100000016",
            company_id="20000014",
            street="Bulevar Ogleda 22",
            city="Beograd",
            postal_code="11000",
            country="RS",
        ),
        lines=[
            Line(
                name="Konsultantski sat",
                quantity="8",
                unit="HUR",
                unit_price="1500.00",
                net_amount="12000.00",
                vat_category="S",
                vat_rate="20",
            )
        ],
        vat_breakdown=[
            VatSubtotal(
                vat_category="S", vat_rate="20", taxable_amount="12000.00", tax_amount="2400.00"
            )
        ],
        totals=Totals(
            line_total="12000.00",
            tax_exclusive="12000.00",
            tax="2400.00",
            tax_inclusive="14400.00",
            payable="14400.00",
        ),
        payment=Payment(account="160-0000000123456-78", model="97", reference="12-345678-00123"),
    )
