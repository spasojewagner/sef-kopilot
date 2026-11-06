"""``POST /invoices/validate``: the validator's report through the API, its limits, hostile
documents, a busy or absent validator, and what never reaches a log."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import Counter
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from lxml import etree
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.pool import QueuePool

from einvoice_core import pipeline
from einvoice_core.pipeline import ValidationReport
from sef_api.db import Database, get_session
from sef_api.invoices import validation
from sef_api.invoices.validation import Patched, Validation
from sef_api.invoices.validator import (
    ValidationRefusedError,
    ValidationTimeoutError,
    ValidatorFailedError,
    ValidatorUnavailableError,
)
from sef_api.main import create_app

from .conftest import REPOSITORY_ROOT, settings_for
from .factories import Office, office

FIXTURES = REPOSITORY_ROOT / "fixtures" / "invoices"
VALID = (FIXTURES / "synthetic" / "srb-final-invoice.xml").read_bytes()
EXAMPLE = "fixtures/invoices/official/sef/avansna-faktura.xml"
XML = {"Content-Type": "application/xml"}
DOCTYPE_REFUSED = "documents with a DOCTYPE declaration are not accepted"


@pytest.fixture
async def primer(session: AsyncSession) -> Office:
    return await office(session, "Primer Računovodstvo", "primer.example")


async def validate(
    api: AsyncClient, primer: Office, content: Any, *, profile: str | None = None
) -> Any:
    return await api.post(
        "/invoices/validate",
        params={"profile": profile} if profile else None,
        content=content,
        headers=XML | primer.as_client(),
    )


@asynccontextmanager
async def application(
    session: AsyncSession, change: Callable[[FastAPI], None] | None = None, **variables: str
) -> AsyncIterator[AsyncClient]:
    """A client of an application with its own settings, on the test's session; ``change``
    may replace parts of the application before it serves."""
    app = create_app(settings_for(**variables))
    if change is not None:
        change(app)

    async def the_test_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = the_test_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    await app.state.database.engine.dispose()


class Scripted:
    """A validator that answers as a test says: a report, an error, or nothing until let go."""

    def __init__(self, *, problem: str | None = None, error: Exception | None = None) -> None:
        self.problem = problem
        self.error = error
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.held = False

    async def start(self) -> None:
        pass

    async def validate(self, _content: bytes, profile: str) -> Validation:
        self.entered.set()
        if self.problem is not None:
            raise ValidatorUnavailableError(self.problem)
        if self.held:
            await self.release.wait()
        if self.error is not None:
            raise self.error
        report = ValidationReport(profile=profile, valid=True, violations=(), layers=())
        return Validation(report=report, summary=None)

    async def patch(self, _content: bytes, _profile: str, _patches: object) -> Patched:
        raise AssertionError("not patched in these tests")

    async def stop(self) -> None:
        pass


def using(scripted: Scripted) -> Callable[[FastAPI], None]:
    def change(app: FastAPI) -> None:
        app.state.validator = scripted

    return change


# --- reports ----------------------------------------------------------------------------------


async def test_a_valid_invoice_gets_a_clean_report(api: AsyncClient, primer: Office) -> None:
    response = await validate(api, primer, VALID)

    assert response.status_code == 200
    report = response.json()
    assert (report["profile"], report["valid"], report["violations"]) == ("srb", True, [])
    assert all(layer["ran"] for layer in report["layers"])
    assert response.headers["Cache-Control"] == "no-store"


async def test_the_report_is_the_one_the_validator_recorded_for_the_ministrys_example(
    api: AsyncClient, primer: Office
) -> None:
    recorded = json.loads((FIXTURES / "verdicts.json").read_text(encoding="utf-8"))
    verdict = recorded["documents"][EXAMPLE]["srb"]

    report = (await validate(api, primer, (REPOSITORY_ROOT / EXAMPLE).read_bytes())).json()

    fatal = Counter(v["rule_id"] for v in report["violations"] if v["severity"] == "fatal")
    assert report["valid"] is verdict["valid"] is False
    assert dict(fatal) == verdict["fatal"]


@pytest.mark.parametrize("profile", ["en16931", "peppol"])
async def test_a_profile_can_be_chosen(api: AsyncClient, primer: Office, profile: str) -> None:
    report = (await validate(api, primer, VALID, profile=profile)).json()

    assert report["profile"] == profile


async def test_an_unknown_profile_is_refused(api: AsyncClient, primer: Office) -> None:
    assert (await validate(api, primer, VALID, profile="xrechnung")).status_code == 422


async def test_a_document_the_validator_cannot_read_is_a_violation_not_an_error(
    api: AsyncClient, primer: Office
) -> None:
    response = await validate(api, primer, b"this is not an invoice")

    assert response.status_code == 200
    assert response.json()["valid"] is False
    assert response.json()["violations"][0]["code"] == "UNREADABLE"


# --- hostile documents ------------------------------------------------------------------------


async def test_an_external_entity_is_never_resolved(
    api: AsyncClient, primer: Office, tmp_path: Path
) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("the-contents-of-a-private-file", encoding="utf-8")
    document = (
        f'<?xml version="1.0"?><!DOCTYPE Invoice [<!ENTITY x SYSTEM "{secret.as_uri()}">]>'
        "<Invoice>&x;</Invoice>"
    ).encode()

    response = await validate(api, primer, document)

    assert response.status_code == 200
    (violation,) = response.json()["violations"]
    assert (violation["code"], violation["message"]) == ("UNREADABLE", DOCTYPE_REFUSED)
    assert "the-contents-of-a-private-file" not in response.text


async def test_entity_expansion_is_refused_at_once(api: AsyncClient, primer: Office) -> None:
    """The "billion laughs": nested entities that would expand to gigabytes. The parser
    refuses it before anything is expanded (libxml2 bounds the amplification of entities)."""
    entities = '<!ENTITY a0 "lol">' + "".join(
        f'<!ENTITY a{i} "{f"&a{i - 1};" * 10}">' for i in range(1, 10)
    )
    document = f"<!DOCTYPE Invoice [{entities}]><Invoice>&a9;</Invoice>".encode()

    started = time.perf_counter()
    response = await validate(api, primer, document)

    assert time.perf_counter() - started < 2
    (violation,) = response.json()["violations"]
    assert violation["code"] == "UNREADABLE"
    assert "entity" in violation["message"] or violation["message"] == DOCTYPE_REFUSED


# --- limits -----------------------------------------------------------------------------------


async def test_a_declared_length_over_the_limit_is_refused_before_anything_is_read(
    session: AsyncSession, primer: Office
) -> None:
    pulled: list[int] = []

    async def body() -> AsyncIterator[bytes]:
        pulled.append(1)
        yield b"<" + b"x" * 1024

    async with application(session, SEF_MAX_INVOICE_BYTES="1024") as api:
        response = await api.post(
            "/invoices/validate",
            content=body(),
            headers=XML | {"Content-Length": "1025"} | primer.as_client(),
        )

    assert response.status_code == 413
    assert response.json() == {"detail": "the invoice is larger than 1024 bytes"}
    assert pulled == []


async def test_a_body_without_a_length_is_refused_as_soon_as_it_passes_the_limit(
    session: AsyncSession, primer: Office
) -> None:
    pulled: list[int] = []

    async def chunks() -> AsyncIterator[bytes]:  # no Content-Length: counted while it is read
        for _ in range(100):
            pulled.append(1)
            yield b"x" * 512

    async with application(session, SEF_MAX_INVOICE_BYTES="1024") as api:
        streamed = await api.post(
            "/invoices/validate", content=chunks(), headers=XML | primer.as_client()
        )
        at_the_limit = await validate(api, primer, b"x" * 1024)

    assert streamed.status_code == 413
    assert streamed.json() == {"detail": "the invoice is larger than 1024 bytes"}
    assert len(pulled) == 3  # 1536 bytes read of 51 200: the rest is never held
    assert at_the_limit.status_code == 200


async def test_an_invoice_that_arrives_too_slowly_is_refused(
    session: AsyncSession, primer: Office
) -> None:
    async def slowly() -> AsyncIterator[bytes]:
        yield VALID[:100]
        await asyncio.sleep(5)
        yield VALID[100:]

    async with application(session, SEF_UPLOAD_SECONDS="0.2") as api:
        started = time.perf_counter()
        response = await api.post(
            "/invoices/validate", content=slowly(), headers=XML | primer.as_client()
        )

    assert response.status_code == 408
    assert response.json() == {"detail": "the invoice was not received within 0.2 s"}
    assert time.perf_counter() - started < 2


async def test_an_invoice_with_too_many_elements_is_refused(
    session: AsyncSession, primer: Office
) -> None:
    async with application(session, SEF_MAX_INVOICE_ELEMENTS="100") as api:
        response = await validate(api, primer, VALID)  # 126 elements

    assert response.status_code == 413
    assert response.json() == {"detail": "the invoice has more than 100 elements"}


@pytest.mark.parametrize(
    "content_type", [None, "text/plain", "application/json", "multipart/form-data; boundary=x"]
)
async def test_an_invoice_must_be_sent_as_xml(
    api: AsyncClient, primer: Office, content_type: str | None
) -> None:
    headers = primer.as_client() | ({"Content-Type": content_type} if content_type else {})

    response = await api.post("/invoices/validate", content=VALID, headers=headers)

    assert response.status_code == 415


async def test_text_xml_with_a_charset_is_xml_too(api: AsyncClient, primer: Office) -> None:
    response = await api.post(
        "/invoices/validate",
        content=VALID,
        headers={"Content-Type": "text/xml; charset=utf-8"} | primer.as_client(),
    )

    assert response.json()["valid"] is True


# --- who may ----------------------------------------------------------------------------------


async def test_every_member_may_have_an_invoice_validated(api: AsyncClient, primer: Office) -> None:
    for headers in (primer.as_owner(), primer.as_accountant(), primer.as_client()):
        response = await api.post("/invoices/validate", content=VALID, headers=XML | headers)
        assert response.status_code == 200


async def test_without_an_access_token_nothing_is_validated(api: AsyncClient) -> None:
    response = await api.post("/invoices/validate", content=VALID, headers=XML)

    assert response.status_code == 401


# --- a busy, slow or absent validator ---------------------------------------------------------


async def test_a_validator_that_cannot_run_answers_503(
    session: AsyncSession, primer: Office
) -> None:
    scripted = Scripted(problem="the validator's rule sets are not installed")

    async with application(session, using(scripted)) as api:
        response = await validate(api, primer, VALID)

    assert response.status_code == 503
    assert response.json() == {"detail": "the validator is not available"}


async def test_validations_beyond_the_capacity_are_turned_away_with_retry_after(
    session: AsyncSession, primer: Office
) -> None:
    scripted = Scripted()
    scripted.held = True

    pulled: list[bytes] = []

    async def body() -> AsyncIterator[bytes]:
        pulled.append(VALID)
        yield VALID

    async with application(session, using(scripted), SEF_MAX_VALIDATIONS_IN_FLIGHT="1") as api:
        first = asyncio.create_task(validate(api, primer, VALID))
        await asyncio.wait_for(scripted.entered.wait(), 5)
        turned_away = await api.post(
            "/invoices/validate", content=body(), headers=XML | primer.as_client()
        )
        scripted.release.set()
        admitted = await first

    assert turned_away.status_code == 503
    assert turned_away.headers["Retry-After"] == "1"
    assert turned_away.json() == {"detail": "the validator is busy"}
    assert pulled == []  # turned away before its body was read
    assert admitted.status_code == 200


async def test_a_queue_that_fills_while_the_body_arrives_turns_the_request_away(
    session: AsyncSession, primer: Office
) -> None:
    """Admission is checked again once the body is in: the fast check before it may be stale."""
    scripted = Scripted()
    scripted.held = True
    started = asyncio.Event()
    finish = asyncio.Event()

    async def slowly() -> AsyncIterator[bytes]:
        started.set()
        yield VALID[:100]
        await finish.wait()
        yield VALID[100:]

    async with application(session, using(scripted), SEF_MAX_VALIDATIONS_IN_FLIGHT="1") as api:
        late = asyncio.create_task(
            api.post("/invoices/validate", content=slowly(), headers=XML | primer.as_client())
        )
        await asyncio.wait_for(started.wait(), 5)  # past the fast check, reading its body
        first = asyncio.create_task(validate(api, primer, VALID))
        await asyncio.wait_for(scripted.entered.wait(), 5)  # the only place is taken
        finish.set()
        turned_away = await late
        scripted.release.set()
        admitted = await first

    assert (turned_away.status_code, turned_away.headers["Retry-After"]) == (503, "1")
    assert admitted.status_code == 200


@pytest.mark.parametrize(
    ("error", "status", "detail"),
    [
        (
            ValidationTimeoutError("the invoice could not be validated within 15 s"),
            422,
            "the invoice could not be validated within 15 s",
        ),
        (
            ValidationRefusedError("the rule sets could not be applied to this invoice"),
            422,
            "the rule sets could not be applied to this invoice",
        ),
        (
            ValidatorFailedError("the validator stopped"),
            500,
            "the validator failed on this document",
        ),
    ],
)
async def test_what_the_validator_could_not_do_is_said_without_content(
    session: AsyncSession,
    primer: Office,
    caplog: pytest.LogCaptureFixture,
    error: Exception,
    status: int,
    detail: str,
) -> None:
    with caplog.at_level(logging.ERROR, logger="sef_api.invoices.routes"):
        async with application(session, using(Scripted(error=error))) as api:
            response = await validate(api, primer, VALID)

    assert (response.status_code, response.json()) == (status, {"detail": detail})
    if status == 500:
        assert "validation failed with the validator stopped" in caplog.text


# --- failures and logs ------------------------------------------------------------------------

MARKER = "PIB-100000024-and-a-secret-amount"


def with_marker(content: bytes) -> bytes:
    """The invoice with a note that only its content contains."""
    return content.replace(b"<cbc:Note>", f"<cbc:Note>{MARKER}</cbc:Note><cbc:Note>".encode(), 1)


async def test_no_invoice_content_reaches_a_log_or_a_standard_stream(
    api: AsyncClient,
    primer: Office,
    caplog: pytest.LogCaptureFixture,
    capfd: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Python's log records and the process's own file descriptors, which native code writes
    to directly, both stay free of the document."""
    document = with_marker(VALID)
    assert MARKER.encode() in document

    def failing(source: Any, _profile: str) -> Any:
        quoted = source.decode() if isinstance(source, bytes) else etree.tostring(source).decode()
        raise RuntimeError(f"the validator choked on {quoted}")

    with caplog.at_level(logging.DEBUG):
        await validate(api, primer, document)  # a report
        await validate(api, primer, document.replace(b"<", b"[", 3))  # unreadable
        monkeypatch.setattr(validation, "validate", failing)
        failed = await validate(api, primer, document)  # the validator itself fails
        monkeypatch.undo()

    assert failed.status_code == 500
    assert failed.json() == {"detail": "the validator failed on this document"}
    assert "validation failed with RuntimeError" in caplog.text
    assert MARKER not in caplog.text
    captured = capfd.readouterr()
    assert MARKER not in captured.out + captured.err


async def test_an_error_of_the_validator_is_logged_by_its_type_alone(
    session: AsyncSession, primer: Office, caplog: pytest.LogCaptureFixture
) -> None:
    """An error's message may quote the invoice. Only the validator's own failure, worded by the
    validator, is logged as it is."""
    with caplog.at_level(logging.ERROR, logger="sef_api.invoices.routes"):
        async with application(session, using(Scripted(error=RuntimeError(MARKER)))) as api:
            response = await validate(api, primer, VALID)

    assert response.status_code == 500
    assert response.json() == {"detail": "the validator failed on this document"}
    assert "validation failed with RuntimeError" in caplog.text
    assert MARKER not in caplog.text


def with_two_vat_identifiers(content: bytes) -> bytes:
    """The invoice with a Greek seller who has two VAT identifiers, which makes the Peppol
    rules warn on Saxon's error stream, quoting the second one's country prefix."""
    second = (
        b"<cac:PartyTaxScheme><cbc:CompanyID>EL100000024</cbc:CompanyID>"
        b"<cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:PartyTaxScheme>"
    )
    greek = content.replace(b">RS</cbc:IdentificationCode>", b">GR</cbc:IdentificationCode>", 1)
    greek = greek.replace(b">RS100000024<", b">EL100000024<", 1)
    return greek.replace(b"<cac:PartyLegalEntity>", second + b"<cac:PartyLegalEntity>", 1)


async def test_saxon_says_nothing_on_the_standard_streams(
    api: AsyncClient, primer: Office, capfd: pytest.CaptureFixture[str]
) -> None:
    response = await api.post(
        "/invoices/validate?profile=peppol",
        content=with_two_vat_identifiers(VALID),
        headers=XML | primer.as_client(),
    )

    assert response.status_code == 200
    assert capfd.readouterr() == ("", "")


# --- resources, budget and contract -----------------------------------------------------------


async def test_no_database_connection_is_held_while_the_invoice_is_read_or_validated(
    committed_database: Database, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The permission check is the request's only database work: neither a slow upload nor a
    validation waiting for its turn may keep a pooled connection from other requests."""
    async with committed_database.sessions() as setup:
        primer = await office(setup, "Primer Računovodstvo", "primer.example")
        await setup.commit()
    app = create_app(settings_for(database_url))
    pool = app.state.database.engine.pool
    assert isinstance(pool, QueuePool)
    held: list[int] = []
    real = pipeline.validate

    async def upload() -> AsyncIterator[bytes]:  # read by the application, chunk by chunk
        held.append(pool.checkedout())
        yield VALID

    def validating(content: bytes, profile: str) -> Any:
        held.append(pool.checkedout())
        return real(content, profile)

    monkeypatch.setattr(validation, "validate", validating)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
        response = await api.post(
            "/invoices/validate", content=upload(), headers=XML | primer.as_client()
        )
    await app.state.database.engine.dispose()

    assert response.status_code == 200
    assert held == [0, 0]


async def test_a_warm_validation_stays_within_the_budget(api: AsyncClient, primer: Office) -> None:
    """The performance budget: a typical invoice in under 500 ms once the validator is warm."""
    await validate(api, primer, VALID)

    started = time.perf_counter()
    response = await validate(api, primer, VALID)

    assert response.status_code == 200
    assert time.perf_counter() - started < 0.5


async def test_openapi_documents_the_xml_body_and_the_report(client: AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()
    operation = schema["paths"]["/invoices/validate"]["post"]

    assert operation["tags"] == ["invoices"]
    assert operation["security"] == [{"access token or API key": []}]
    assert set(operation["requestBody"]["content"]) == {"application/xml", "text/xml"}
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ValidationReport"
    }
    assert {"408", "413", "415", "422", "503"} <= set(operation["responses"])
