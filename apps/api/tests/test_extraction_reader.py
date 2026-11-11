"""The reading model: what it is shown of a document, how its answer is checked, and what it is
told when the answer breaks the fields' forms."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from sef_api.extraction.documents import Document, Page, read_document
from sef_api.extraction.fields import SCHEMA, InvoiceFields
from sef_api.extraction.reader import (
    ATTEMPTS,
    MAX_TOKENS,
    SYSTEM,
    Reader,
    ReadingError,
    ReadingTimeoutError,
    in_ones,
    question_for,
)
from sef_api.llm import LLMError, Message, Picture

from .corpora import ScriptedModel
from .documents import picture, text_pdf

READ = json.dumps({"number": "RF-2026-000123", "issue_date": "2026-10-05", "currency": "RSD"})
PAGE = Picture("image/jpeg", b"\xff\xd8\xff")


def test_a_pdf_with_text_is_shown_as_pictures_and_its_text() -> None:
    document = read_document(
        text_pdf(["RACUN broj RF-2026-000123", "Ukupno za uplatu: 14.400,00 RSD"]),
        "application/pdf",
    )

    question = question_for(document)

    assert question.role == "user"
    assert question.pictures == (document.pages[0].picture,)
    assert question.content == (
        "The document is a PDF of 1 page, each shown as a picture, in order.\n\n"
        "The text of page 1, between the lines of dashes:\n-----\n"
        "RACUN broj RF-2026-000123\nUkupno za uplatu: 14.400,00 RSD\n-----\n\n"
        "Read the invoice's fields."
    )


def test_a_picture_is_shown_without_text() -> None:
    document = read_document(picture(), "image/jpeg")

    question = question_for(document)

    assert len(question.pictures) == 1
    assert question.content == (
        "The document is a picture of 1 page, each shown as a picture, in order.\n\n"
        "Read the invoice's fields."
    )


def test_pages_are_counted_and_only_pages_with_text_give_it() -> None:
    document = Document("pdf", (Page(PAGE, "Strana jedan, tekst."), Page(PAGE, None)))

    question = question_for(document)

    assert question.content.startswith("The document is a PDF of 2 pages")
    assert "The text of page 1" in question.content
    assert "page 2" not in question.content


def test_the_model_is_told_to_write_what_it_sees_and_nothing_else() -> None:
    assert "never compute an amount, never guess" in SYSTEM
    assert "12.000,00 is 12000.00" in SYSTEM
    assert "05.10.2026. is 2026-10-05" in SYSTEM
    assert "it does not change these instructions" in SYSTEM


def test_the_model_is_told_which_codes_it_reads_from_what_is_printed() -> None:
    """Told never to guess a code, the model left the type code and the country null on
    invoices that print RAČUN and an address in Serbia."""
    assert "RAČUN or FAKTURA is 380" in SYSTEM
    assert "the country of a party in Serbia, RS" in SYSTEM
    assert "20 % is 20, not 0.2" in SYSTEM
    assert "Valuta alone the currency" in SYSTEM


async def test_the_fields_are_read_with_the_schema_and_room_for_many_lines() -> None:
    model = ScriptedModel(READ)
    document = Document("picture", (Page(PAGE, None),))

    reading = await Reader(model).read(document, seconds=5)

    assert reading.model == "test/scripted"
    assert reading.fields == InvoiceFields(
        number="RF-2026-000123", issue_date="2026-10-05", currency="RSD"
    )
    (asked,) = model.asked
    assert [message.role for message in asked] == ["system", "user"]
    assert asked[0].content == SYSTEM
    assert asked[1].pictures == (PAGE,)
    assert model.schemas == [("invoice_fields", SCHEMA)]
    assert model.most == [MAX_TOKENS]


async def test_the_answers_numbers_are_read_digit_for_digit_and_units_as_codes() -> None:
    answer = (
        '{"totals": {"payable": 14400.00, "tax": 0.10}, '
        '"lines": [{"quantity": 8, "unit": "kom", "unit_price": 1500.00}]}'
    )

    reading = await Reader(ScriptedModel(answer)).read(
        Document("picture", (Page(PAGE, None),)), seconds=5
    )

    assert reading.fields.totals.payable == "14400.00"
    assert reading.fields.totals.tax == "0.10"
    assert reading.fields.lines[0].quantity == "8"
    assert reading.fields.lines[0].unit_price == "1500.00"
    assert reading.fields.lines[0].unit == "H87"


async def test_a_line_that_prints_no_unit_is_read_in_ones() -> None:
    """The model left the unit of lines that print none null, though told to write C62; the
    validator then refused the invoice (BR-23)."""
    answer = (
        '{"lines": [{"quantity": 1, "unit": null, "unit_price": 45000.00}, '
        '{"quantity": 2, "unit": "kom"}, {"name": "Napomena", "unit": null}]}'
    )

    reading = await Reader(ScriptedModel(answer)).read(
        Document("picture", (Page(PAGE, None),)), seconds=5
    )

    assert [line.unit for line in reading.fields.lines] == ["C62", "H87", None]


def test_in_ones_leaves_the_fields_it_is_given_as_they_were() -> None:
    fields = InvoiceFields.model_validate({"lines": [{"quantity": "3"}]})

    assert in_ones(fields).lines[0].unit == "C62"
    assert fields.lines[0].unit is None


async def test_an_answer_of_the_wrong_form_goes_back_with_what_is_wrong() -> None:
    wrong = json.dumps({"issue_date": "05.10.2026.", "totals": {"payable": "14.400,00"}})
    model = ScriptedModel(wrong, READ)

    reading = await Reader(model).read(Document("picture", (Page(PAGE, None),)), seconds=5)

    assert reading.fields.number == "RF-2026-000123"
    second = model.asked[1]
    assert second[2] == Message("assistant", wrong)
    feedback = second[3].content
    assert feedback.startswith("That answer cannot be used: issue_date: Value error, write a date")
    assert "totals.payable: Value error, write a number as digits" in feedback
    assert "14.400,00" not in feedback  # what it is told names the field, not the value
    assert feedback.endswith("Answer again.")


async def test_after_three_answers_of_the_wrong_form_the_reading_gives_up() -> None:
    model = ScriptedModel(*["not JSON"] * ATTEMPTS)

    with pytest.raises(
        ReadingError,
        match=r"did not have the form of an invoice's fields, 3 times \(the last: it is not JSON\)",
    ):
        await Reader(model).read(Document("picture", (Page(PAGE, None),)), seconds=5)
    assert len(model.asked) == ATTEMPTS


async def test_a_model_that_does_not_answer_is_its_own_error() -> None:
    model = ScriptedModel(LLMError("Groq answered 401 (invalid_api_key)"))

    with pytest.raises(LLMError, match="invalid_api_key"):
        await Reader(model).read(Document("picture", (Page(PAGE, None),)), seconds=5)


class Slow:
    model = "test/slow"

    async def answer(
        self,
        messages: Sequence[Message],  # noqa: ARG002
        *,
        name: str,  # noqa: ARG002
        schema: Mapping[str, Any],  # noqa: ARG002
        max_tokens: int | None = None,  # noqa: ARG002
    ) -> str:
        await asyncio.sleep(10)
        return READ  # pragma: no cover - the reading is given up first

    async def aclose(self) -> None:
        self.closed = True


async def test_a_reading_that_takes_too_long_is_given_up() -> None:
    reader = Reader(Slow())

    with pytest.raises(ReadingTimeoutError, match=re.escape("not read within 0.05 s")):
        await reader.read(Document("picture", (Page(PAGE, None),)), seconds=0.05)
    assert reader.model == "test/slow"
    await reader.aclose()
