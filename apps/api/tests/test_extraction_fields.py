"""The fields of an invoice as a document prints them: the forms their values must have, the
schema the reading model answers in strict mode, and the fields of a known invoice."""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from einvoice_core.ubl import parse_invoice
from sef_api.extraction.draft import draft
from sef_api.extraction.fields import (
    MAX_LINES,
    SCHEMA,
    UNITS,
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


def test_amounts_are_asked_for_as_numbers_and_the_rest_as_text() -> None:
    """Asked for as text, a model held to the schema by constrained decoding wrote every amount
    as null: it could not begin with the digit it meant to write."""
    line = SCHEMA["properties"]["lines"]["items"]["properties"]
    row = SCHEMA["properties"]["vat_breakdown"]["items"]["properties"]
    totals = SCHEMA["properties"]["totals"]["properties"]
    numbers = [
        line["quantity"],
        line["unit_price"],
        line["net_amount"],
        line["vat_rate"],
        row["vat_rate"],
        row["taxable_amount"],
        row["tax_amount"],
        *totals.values(),
    ]
    assert all(each["type"] == ["number", "null"] and each["description"] for each in numbers)
    assert line["unit"]["type"] == ["string", "null"]
    assert SCHEMA["properties"]["issue_date"]["type"] == ["string", "null"]
    assert SCHEMA["properties"]["seller"]["properties"]["tax_id"]["type"] == ["string", "null"]


def test_the_api_gives_amounts_as_text_as_it_answers_them() -> None:
    """Only the model is asked for numbers: the API's document, and the web client typed from
    it, keep the amounts as text, as the API answers them."""
    text = [{"type": "string"}, {"type": "null"}]
    for schema in (
        InvoiceFields.model_json_schema(mode="validation"),
        InvoiceFields.model_json_schema(mode="serialization"),
    ):
        definitions = schema["$defs"]
        assert definitions["Line"]["properties"]["quantity"]["anyOf"] == text
        assert definitions["VatSubtotal"]["properties"]["vat_rate"]["anyOf"] == text
        assert definitions["Totals"]["properties"]["payable"]["anyOf"] == text


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


@pytest.mark.parametrize(
    ("number", "text"),
    [
        (Decimal("14400.00"), "14400.00"),
        (Decimal("0.10"), "0.10"),
        (Decimal("1E+3"), "1000"),
        (8, "8"),
        (1500.5, "1500.5"),
        ("12000.00", "12000.00"),
    ],
)
def test_an_amount_written_as_a_number_is_kept_as_text_digit_for_digit(
    number: object, text: str
) -> None:
    assert Totals.model_validate({"payable": number}).payable == text


@pytest.mark.parametrize("rate", [Decimal("0.2"), 0.1, "0.20"])
def test_a_vat_rate_written_as_a_fraction_says_to_write_it_in_percent(rate: object) -> None:
    """The first readings with numbers wrote 20 % as 0.2 on every invoice."""
    with pytest.raises(ValidationError, match="write the rate in percent"):
        Line.model_validate({"vat_rate": rate})
    with pytest.raises(ValidationError, match="write the rate in percent"):
        VatSubtotal.model_validate({"vat_rate": rate})


@pytest.mark.parametrize(("rate", "text"), [(Decimal("20"), "20"), (10, "10"), (0, "0")])
def test_a_vat_rate_in_percent_is_kept(rate: object, text: str) -> None:
    assert Line.model_validate({"vat_rate": rate}).vat_rate == text


def test_a_pib_and_a_registration_number_the_other_way_round_go_back_to_the_model() -> None:
    with pytest.raises(ValidationError, match="write each in its own field") as raised:
        InvoiceFields.model_validate({"seller": {"tax_id": "20000022", "company_id": "100000032"}})
    assert raised.value.errors()[0]["loc"] == ("seller",)
    party = Party(tax_id="100000032", company_id="20000022")
    assert (party.tax_id, party.company_id) == ("100000032", "20000022")
    # Either alone is not judged: a foreign buyer's tax number has a form of its own.
    assert Party(tax_id="20000022").tax_id == "20000022"


def test_true_or_false_is_not_an_amount() -> None:
    with pytest.raises(ValidationError, match="valid string"):
        Totals.model_validate({"payable": True})


@pytest.mark.parametrize(
    ("printed", "code"),
    [
        ("kom", "H87"),
        ("Kom.", "H87"),
        ("ком", "H87"),
        ("sat", "HUR"),
        ("dan", "DAY"),
        ("kg", "KGM"),
        ("l", "LTR"),
        ("km", "KMT"),
        ("m²", "MTK"),
        ("H87", "H87"),
        ("c62", "C62"),
    ],
)
def test_a_unit_written_as_printed_is_made_its_code(printed: str, code: str) -> None:
    assert Line(unit=printed).unit == code


def test_a_unit_neither_printed_nor_a_code_says_which_form() -> None:
    with pytest.raises(ValidationError, match="write the unit as the line prints it"):
        Line(unit="x")


def test_every_printed_unit_is_lower_case_and_stands_for_a_code() -> None:
    assert all(printed == printed.casefold() for printed in UNITS)
    assert all(re.fullmatch(r"[A-Z0-9]{2,3}", code) for code in UNITS.values())


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
