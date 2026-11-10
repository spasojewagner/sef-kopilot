"""``POST /invoices/extract`` and ``POST /invoices/draft``: an invoice read from a PDF or a picture
by the reading model, and the UBL invoice made of its fields once a person confirmed them."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from einvoice_core.pipeline import validate
from sef_api.extraction.draft import draft
from sef_api.extraction.fields import InvoiceFields, Line, Party, Totals
from sef_api.extraction.reader import Reader
from sef_api.llm import LLMError

from .corpora import ScriptedModel
from .documents import picture, scanned_pdf, text_pdf
from .factories import Office, office
from .test_extraction_reader import READ, Slow
from .test_invoices_validate import application

PDF = {"Content-Type": "application/pdf"}
JPEG = {"Content-Type": "image/jpeg"}


@pytest.fixture
async def primer(session: AsyncSession) -> Office:
    return await office(session, "Primer Računovodstvo", "primer.example")


@asynccontextmanager
async def reading(
    session: AsyncSession, model: Any = None, **variables: str
) -> AsyncIterator[AsyncClient]:
    """A client of an application that reads documents with ``model``, or reads none."""

    def change(app: FastAPI) -> None:
        app.state.reader = Reader(model) if model is not None else None

    async with application(session, change, **variables) as api:
        yield api


async def test_a_scanned_pdf_is_read_into_fields_and_nothing_kept(
    session: AsyncSession, primer: Office
) -> None:
    model = ScriptedModel(READ)
    async with reading(session, model) as api:
        read = await api.post(
            "/invoices/extract", content=scanned_pdf(), headers=PDF | primer.as_client()
        )

    assert read.status_code == 200, read.text
    assert read.headers["Cache-Control"] == "no-store"
    body = read.json()
    assert body["document"] == {"kind": "pdf", "pages": 1, "text": False}
    assert body["model"] == "test/scripted"
    assert InvoiceFields.model_validate(body["fields"]) == InvoiceFields(
        number="RF-2026-000123", issue_date="2026-10-05", currency="RSD"
    )
    (asked,) = model.asked
    assert len(asked[1].pictures) == 1


async def test_a_pdf_with_text_gives_the_model_its_text(
    session: AsyncSession, primer: Office
) -> None:
    model = ScriptedModel(READ)
    content = text_pdf(["RACUN broj RF-2026-000123", "Za uplatu: 14.400,00 RSD"])
    async with reading(session, model) as api:
        read = await api.post("/invoices/extract", content=content, headers=PDF | primer.as_owner())

    assert read.json()["document"] == {"kind": "pdf", "pages": 1, "text": True}
    assert "Za uplatu: 14.400,00 RSD" in model.asked[0][1].content


async def test_a_photograph_is_read(session: AsyncSession, primer: Office) -> None:
    async with reading(session, ScriptedModel(READ)) as api:
        read = await api.post(
            "/invoices/extract", content=picture(), headers=JPEG | primer.as_accountant()
        )

    assert read.status_code == 200
    assert read.json()["document"] == {"kind": "picture", "pages": 1, "text": False}


async def test_without_a_model_nothing_is_read(session: AsyncSession, primer: Office) -> None:
    async with reading(session) as api:
        read = await api.post(
            "/invoices/extract", content=picture(), headers=JPEG | primer.as_client()
        )

    assert read.status_code == 503
    assert read.json()["detail"] == "no language model is configured on this server"


@pytest.mark.parametrize(
    ("content", "headers", "status", "detail"),
    [
        (b"<Invoice/>", {"Content-Type": "application/xml"}, 415, "send the PDF or the picture"),
        (b"plain", {"Content-Type": "text/plain"}, 415, "Content-Type: application/pdf"),
        (b"%PDF-1.7\nbroken", PDF, 422, "the PDF cannot be opened"),
        (picture("PNG"), JPEG, 422, "sent as image/jpeg, but it is image/png"),
        (scanned_pdf(4), PDF, 413, "the PDF has 4 pages; at most 3 are read"),
    ],
)
async def test_a_document_that_cannot_be_read_says_why(
    session: AsyncSession,
    primer: Office,
    content: bytes,
    headers: dict[str, str],
    status: int,
    detail: str,
) -> None:
    model = ScriptedModel(READ)
    async with reading(session, model) as api:
        read = await api.post(
            "/invoices/extract", content=content, headers=headers | primer.as_client()
        )

    assert read.status_code == status
    assert detail in read.json()["detail"]
    assert model.asked == []


async def test_a_document_larger_than_the_settings_allow_is_refused_unread(
    session: AsyncSession, primer: Office
) -> None:
    model = ScriptedModel(READ)
    async with reading(session, model, SEF_MAX_DOCUMENT_BYTES=str(64 * 1024)) as api:
        read = await api.post(
            "/invoices/extract",
            content=picture("PNG", size=(2000, 2000)) + b"\0" * 64 * 1024,
            headers={"Content-Type": "image/png"} | primer.as_client(),
        )

    assert read.status_code == 413
    assert read.json()["detail"] == "the document is larger than 65536 bytes"
    assert model.asked == []


async def test_a_document_longer_than_other_bodies_may_be_is_read_within_its_own_limit(
    session: AsyncSession, primer: Office
) -> None:
    photograph = picture(size=(2400, 3200))
    assert len(photograph) > 64 * 1024
    async with reading(session, ScriptedModel(READ), SEF_MAX_BODY_BYTES=str(64 * 1024)) as api:
        read = await api.post(
            "/invoices/extract", content=photograph, headers=JPEG | primer.as_client()
        )
        other = await api.post(
            "/invoices/draft",
            content=b'{"note": "' + b"x" * 64 * 1024 + b'"}',
            headers={"Content-Type": "application/json"} | primer.as_client(),
        )

    assert read.status_code == 200, read.text
    assert other.status_code == 413


@pytest.mark.parametrize(
    ("answers", "status", "detail"),
    [
        (
            [LLMError("Groq answered 401 (invalid_api_key)")],
            502,
            "did not answer: Groq answered 401",
        ),
        (["no JSON"] * 3, 422, "did not have the form of an invoice's fields, 3 times"),
    ],
)
async def test_a_model_that_reads_nothing_usable_says_why(
    session: AsyncSession,
    primer: Office,
    answers: list[str | Exception],
    status: int,
    detail: str,
) -> None:
    async with reading(session, ScriptedModel(*answers)) as api:
        read = await api.post(
            "/invoices/extract", content=picture(), headers=JPEG | primer.as_client()
        )

    assert read.status_code == status
    assert detail in read.json()["detail"]


async def test_a_reading_that_takes_too_long_answers_504(
    session: AsyncSession, primer: Office
) -> None:
    async with reading(session, Slow(), SEF_EXTRACTION_SECONDS="0.05") as api:
        read = await api.post(
            "/invoices/extract", content=picture(), headers=JPEG | primer.as_client()
        )

    assert read.status_code == 504
    assert read.json()["detail"] == "the document was not read within 0.05 s"


async def test_a_reading_counts_as_a_request_to_the_model(
    session: AsyncSession, primer: Office
) -> None:
    model = ScriptedModel(READ, READ)
    async with reading(session, model, SEF_EXPLANATIONS_PER_MINUTE="1") as api:
        first = await api.post(
            "/invoices/extract", content=picture(), headers=JPEG | primer.as_client()
        )
        second = await api.post(
            "/invoices/extract", content=picture(), headers=JPEG | primer.as_client()
        )

    assert (first.status_code, second.status_code) == (200, 429)
    assert "requests to the language model" in second.json()["detail"]
    assert len(model.asked) == 1


async def test_nothing_of_a_document_is_logged_whatever_becomes_of_it(
    session: AsyncSession, primer: Office, caplog: pytest.LogCaptureFixture
) -> None:
    marked = text_pdf(["RACUN TAJNA-4711-MARKER", "Za uplatu 14.400,00 RSD TAJNA-4711-MARKER"])
    caplog.set_level(logging.DEBUG)
    async with reading(session, ScriptedModel(READ, "no JSON", "no JSON", "no JSON")) as api:
        read = await api.post("/invoices/extract", content=marked, headers=PDF | primer.as_client())
        failed = await api.post(
            "/invoices/extract", content=marked, headers=PDF | primer.as_client()
        )

    assert (read.status_code, failed.status_code) == (200, 422)
    assert "TAJNA-4711" not in caplog.text
    assert "TAJNA-4711" not in failed.text


async def test_reading_needs_a_member(session: AsyncSession) -> None:
    async with reading(session, ScriptedModel(READ)) as api:
        read = await api.post("/invoices/extract", content=picture(), headers=JPEG)

    assert read.status_code == 401


# --- the draft ---------------------------------------------------------------------------------

CONFIRMED = InvoiceFields(
    type_code="380",
    number="RF-2026-000200",
    issue_date="2026-11-10",
    currency="RSD",
    seller=Party(name="Primer Softver d.o.o.", tax_id="100000024"),
    lines=[Line(name="Konsultantski sat", quantity="2", unit="HUR", net_amount="3000.00")],
    totals=Totals(payable="3600.00"),
)


async def test_confirmed_fields_are_drafted_into_a_ubl_invoice(
    session: AsyncSession, primer: Office
) -> None:
    async with reading(session) as api:
        drafted = await api.post(
            "/invoices/draft",
            content=CONFIRMED.model_dump_json(),
            headers={"Content-Type": "application/json"} | primer.as_client(),
        )

    assert drafted.status_code == 200, drafted.text
    assert drafted.headers["Content-Type"] == "application/xml"
    assert drafted.headers["Cache-Control"] == "no-store"
    assert drafted.content == draft(CONFIRMED)
    assert validate(drafted.content, profile="srb").violations  # the validator says what is left


async def test_fields_of_the_wrong_form_are_refused_with_what_is_wrong(
    session: AsyncSession, primer: Office
) -> None:
    async with reading(session) as api:
        drafted = await api.post(
            "/invoices/draft",
            json={"issue_date": "10.11.2026.", "totals": {"payable": "3.600,00"}},
            headers=primer.as_client(),
        )

    assert drafted.status_code == 422
    found = json.dumps(drafted.json())
    assert "write a date as YYYY-MM-DD" in found
    assert "write a number as digits with a decimal point" in found


async def test_a_draft_needs_a_member(session: AsyncSession) -> None:
    async with reading(session) as api:
        drafted = await api.post("/invoices/draft", json={})

    assert drafted.status_code == 401
