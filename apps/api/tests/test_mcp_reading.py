"""The MCP server's reading of invoices (ADR-0062, ADR-0064): ``extract_from_pdf`` reads a
document sent in base64 as ``POST /invoices/extract`` reads an upload, and ``draft_invoice``
makes the UBL of the fields as ``POST /invoices/draft`` does."""

from __future__ import annotations

import base64
import json
import logging

import pytest

from einvoice_core.pipeline import validate
from sef_api.db import Database
from sef_api.extraction.draft import draft
from sef_api.extraction.fields import InvoiceFields
from sef_api.extraction.reader import Reader

from .corpora import ScriptedModel
from .documents import picture, scanned_pdf, text_pdf
from .test_extraction_reader import READ
from .test_mcp import NO_MODEL, connected, serving, text_of

pytestmark = pytest.mark.usefixtures("committed_database")


def encoded(document: bytes) -> str:
    return base64.b64encode(document).decode()


async def test_a_picture_is_read_into_fields_as_the_route_reads_it(
    committed_database: Database, database_url: str
) -> None:
    model = ScriptedModel(READ)
    async with serving(committed_database, database_url) as served:
        served.app.state.reader = Reader(model)
        async with connected(served.app, served.key) as client:
            offered = {tool.name: tool for tool in (await client.list_tools()).tools}
            read = await client.call_tool(
                "extract_from_pdf", {"document": encoded(picture()), "media_type": "image/jpeg"}
            )

    assert not read.is_error, text_of(read)
    assert read.structured_content is not None
    assert read.structured_content["fields"]["number"] == "RF-2026-000123"
    assert read.structured_content["document"] == {"kind": "picture", "pages": 1, "text": False}
    assert read.structured_content["model"] == "test/scripted"
    # The model was shown the page as a picture, drawn anew.
    assert len(model.asked[0][-1].pictures) == 1
    tool = offered["extract_from_pdf"]
    assert tool.input_schema["required"] == ["document", "media_type"]
    assert tool.output_schema is not None
    assert tool.output_schema["title"] == "Extraction"
    assert tool.annotations is not None
    # Each call asks the model, whose answers may differ; nothing changes on the server.
    assert (tool.annotations.read_only_hint, tool.annotations.idempotent_hint) == (True, False)
    assert "Show the person the fields beside their document" in str(tool.description)


async def test_a_pdf_gives_its_text_with_its_pictures(
    committed_database: Database, database_url: str
) -> None:
    model = ScriptedModel(READ)
    async with serving(committed_database, database_url) as served:
        served.app.state.reader = Reader(model)
        async with connected(served.app, served.key) as client:
            read = await client.call_tool(
                "extract_from_pdf",
                {
                    "document": encoded(text_pdf(["RACUN RF-2026-000123", "Za uplatu 14.400,00"])),
                    "media_type": "application/pdf",
                },
            )

    assert read.structured_content is not None
    assert read.structured_content["document"] == {"kind": "pdf", "pages": 1, "text": True}
    assert "Za uplatu 14.400,00" in model.asked[0][-1].content


@pytest.mark.parametrize(
    ("document", "media_type", "problem"),
    [
        ("not base64!", "image/jpeg", "the document is not base64"),
        (encoded(scanned_pdf()), "image/jpeg", "the document was sent as image/jpeg, but it is "),
        (encoded(b"%PDF-1.4 nothing more"), "application/pdf", "the PDF cannot be opened"),
        (encoded(scanned_pdf(4)), "application/pdf", "the PDF has 4 pages; at most 3 are read"),
    ],
    ids=["not base64", "not what it says", "damaged", "too many pages"],
)
async def test_a_document_that_cannot_be_read_is_refused_in_the_routes_words(
    committed_database: Database, database_url: str, document: str, media_type: str, problem: str
) -> None:
    async with (
        serving(committed_database, database_url) as served,
        connected(served.app, served.key) as client,
    ):
        refused = await client.call_tool(
            "extract_from_pdf", {"document": document, "media_type": media_type}
        )

    assert refused.is_error
    assert text_of(refused).startswith(f"Error executing tool extract_from_pdf: {problem}")


async def test_a_document_over_the_limit_on_documents_is_refused(
    committed_database: Database, database_url: str
) -> None:
    async with (
        serving(committed_database, database_url, SEF_MAX_DOCUMENT_BYTES=str(64 * 1024)) as served,
        connected(served.app, served.key) as client,
    ):
        refused = await client.call_tool(
            "extract_from_pdf",
            {"document": encoded(b"\xff\xd8\xff" + b"0" * 64 * 1024), "media_type": "image/jpeg"},
        )

    assert text_of(refused) == (
        "Error executing tool extract_from_pdf: the document is larger than 65536 bytes"
    )


async def test_a_server_without_a_model_says_so_before_counting(
    committed_database: Database, database_url: str
) -> None:
    async with (
        serving(
            committed_database, database_url, model=NO_MODEL, SEF_EXPLANATIONS_PER_MINUTE="1"
        ) as served,
        connected(served.app, served.key) as client,
    ):
        arguments = {"document": encoded(picture()), "media_type": "image/jpeg"}
        first = await client.call_tool("extract_from_pdf", arguments)
        second = await client.call_tool("extract_from_pdf", arguments)

    # Refused for the model it does not have, twice: the request a minute was never spent.
    assert [text_of(first), text_of(second)] == [
        "Error executing tool extract_from_pdf: no language model is configured on this server"
    ] * 2


async def test_readings_are_counted_with_the_routes(
    committed_database: Database, database_url: str
) -> None:
    async with (
        serving(committed_database, database_url, SEF_EXPLANATIONS_PER_MINUTE="1") as served,
        connected(served.app, served.key) as client,
        served.http(served.key.header()) as http,
    ):
        arguments = {"document": encoded(picture()), "media_type": "image/jpeg"}
        first = await client.call_tool("extract_from_pdf", arguments)
        routed = await http.post(
            "/invoices/extract", content=picture(), headers={"Content-Type": "image/jpeg"}
        )
        again = await client.call_tool("extract_from_pdf", arguments)

    assert not first.is_error
    assert routed.status_code == 429
    assert text_of(again) == f"Error executing tool extract_from_pdf: {routed.json()['detail']}"


async def test_fields_are_made_into_the_invoice_the_route_makes(
    committed_database: Database, database_url: str
) -> None:
    fields = InvoiceFields.model_validate(json.loads(READ))
    async with (
        serving(committed_database, database_url) as served,
        connected(served.app, served.key) as client,
        served.http(served.key.header()) as http,
    ):
        offered = {tool.name: tool for tool in (await client.list_tools()).tools}
        drafted = await client.call_tool("draft_invoice", {"fields": json.loads(READ)})
        routed = await http.post("/invoices/draft", json=json.loads(READ))

    assert not drafted.is_error
    assert drafted.structured_content == {"xml": draft(fields).decode()}
    assert routed.content == draft(fields)
    # Only some fields: the validator says what is missing, as it would of an upload.
    assert not validate(draft(fields), profile="srb").valid
    tool = offered["draft_invoice"]
    assert tool.annotations is not None
    assert (tool.annotations.read_only_hint, tool.annotations.idempotent_hint) == (True, True)


async def test_drafts_are_counted_as_validations(
    committed_database: Database, database_url: str
) -> None:
    async with (
        serving(committed_database, database_url, SEF_VALIDATIONS_PER_MINUTE="1") as served,
        connected(served.app, served.key) as client,
    ):
        first = await client.call_tool("draft_invoice", {"fields": {}})
        again = await client.call_tool("draft_invoice", {"fields": {}})

    assert not first.is_error
    assert again.is_error
    assert text_of(again).startswith(
        "Error executing tool draft_invoice: too many validations; try again in "
    )


async def test_nothing_of_the_document_reaches_a_log(
    committed_database: Database, database_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    async with (
        serving(committed_database, database_url) as served,
        connected(served.app, served.key) as client,
    ):
        served.app.state.reader = Reader(ScriptedModel(READ))
        read = await client.call_tool(
            "extract_from_pdf",
            {
                "document": encoded(text_pdf(["RACUN RF-2026-000123"])),
                "media_type": "application/pdf",
            },
        )
        drafted = await client.call_tool("draft_invoice", {"fields": json.loads(READ)})

    logged = [
        record.getMessage()
        for record in caplog.records
        if not record.name.startswith(("mcp.client", "httpx"))
    ]
    assert "RF-2026-000123" in str(read.structured_content)
    assert "RF-2026-000123" in str(drafted.structured_content)
    assert logged
    assert not [line for line in logged if "RF-2026-000123" in line]
