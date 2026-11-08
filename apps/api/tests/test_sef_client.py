"""SEF's public API for sales invoices, as the client speaks it: what an import sends, what it
reads back, how a failure ends, and where an invoice stands (ADR-0051). SEF itself answers
through a mock transport, as its published OpenAPI document says it does."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from pydantic import SecretStr, ValidationError

import sef_api.sef.client as client_module
from sef_api.sef.client import FINAL, Imported, SefClient, SefError, SefStatus, Standing

from .conftest import settings_for

BASE = "https://demoefaktura.example"
KEY = SecretStr("4711-4711-4711-4711")
REQUEST = uuid.UUID("0b8e6b4e-7a1c-4f0e-9a3d-2f6c1d5e8a90")
DOCUMENT = b"<Invoice>4711 synthetic</Invoice>"


def sef(
    answer: Callable[[httpx.Request], httpx.Response],
    requests: list[httpx.Request],
    *,
    backoff_seconds: float = 0,
) -> SefClient:
    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return answer(request)

    return SefClient(
        BASE,
        KEY,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        backoff_seconds=backoff_seconds,
    )


def imported(**body: Any) -> httpx.Response:
    return httpx.Response(
        200, json={"invoiceId": 815, "purchaseInvoiceId": 0, "salesInvoiceId": 4711} | body
    )


def invoice(**body: Any) -> httpx.Response:
    """A sales invoice as ``GET /api/publicApi/sales-invoice`` answers it."""
    return httpx.Response(
        200,
        json={
            "invoiceId": 4711,
            "globUniqId": "c0ffee00-0000-4000-8000-000000004711",
            "comment": None,
            "cirStatus": "None",
            "cirInvoiceId": None,
            "version": 2,
            "lastModifiedUtc": "2026-11-08T20:15:03.27",
            "cirSettledAmount": 0,
            "status": "Sent",
        }
        | body,
    )


# --- importing ---------------------------------------------------------------------------------


async def test_an_invoice_is_imported_as_ubl_with_the_organizations_key() -> None:
    requests: list[httpx.Request] = []

    result = await sef(lambda _: imported(), requests).send(DOCUMENT, REQUEST)

    assert result == Imported(sales_invoice_id=4711, invoice_id=815)
    (request,) = requests
    assert (request.method, request.url.path) == ("POST", "/api/publicApi/sales-invoice/ubl")
    assert dict(request.url.params) == {
        "requestId": str(REQUEST),
        "sendToCir": "No",
        "executeValidation": "true",
    }
    assert request.headers["ApiKey"] == "4711-4711-4711-4711"
    assert request.headers["Content-Type"] == "application/xml"
    assert request.headers["Accept"] == "application/json"
    assert request.content == DOCUMENT


async def test_an_import_tried_again_keeps_its_request_id(monkeypatch: pytest.MonkeyPatch) -> None:
    waits: list[float] = []

    class Clock:
        @staticmethod
        async def sleep(seconds: float) -> None:
            waits.append(seconds)

    monkeypatch.setattr(client_module, "asyncio", Clock)
    answers = iter([httpx.Response(503), httpx.Response(429)])
    requests: list[httpx.Request] = []

    def answer(_: httpx.Request) -> httpx.Response:
        return next(answers, None) or imported()

    client = sef(answer, requests, backoff_seconds=6)

    assert (await client.send(DOCUMENT, REQUEST)).sales_invoice_id == 4711
    assert [request.url.params["requestId"] for request in requests] == [str(REQUEST)] * 3
    assert waits == [6.0, SefClient.MAX_WAIT_SECONDS]  # 6, then 12 held to ten


async def test_a_request_that_fails_on_the_way_is_tried_again() -> None:
    failures = iter([httpx.ConnectError("refused"), httpx.ReadTimeout("no answer")])

    def answer(_: httpx.Request) -> httpx.Response:
        if (failure := next(failures, None)) is not None:
            raise failure
        return imported()

    requests: list[httpx.Request] = []
    assert (await sef(answer, requests).send(DOCUMENT, REQUEST)).sales_invoice_id == 4711
    assert len(requests) == SefClient.ATTEMPTS


async def test_sef_that_keeps_failing_is_unavailable_after_three_attempts() -> None:
    requests: list[httpx.Request] = []

    with pytest.raises(SefError, match=r"^SEF: unavailable \(502\)$") as raised:
        await sef(lambda _: httpx.Response(502), requests).send(DOCUMENT, REQUEST)

    assert (raised.value.kind, raised.value.status) == ("unavailable", 502)
    assert len(requests) == SefClient.ATTEMPTS


async def test_sef_that_cannot_be_reached_is_unavailable_without_a_status() -> None:
    def unreachable(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(SefError, match=r"^SEF: unavailable$") as raised:
        await sef(unreachable, []).send(DOCUMENT, REQUEST)

    assert raised.value.status is None


async def test_a_refusal_keeps_sefs_words_for_the_member_and_says_none_of_them() -> None:
    requests: list[httpx.Request] = []
    words = '{"Message": "Faktura 4711 već postoji", "FieldErrors": []}'

    with pytest.raises(SefError) as raised:
        await sef(lambda _: httpx.Response(400, text=words), requests).send(DOCUMENT, REQUEST)

    assert (raised.value.kind, raised.value.status, raised.value.detail) == ("refused", 400, words)
    assert "4711" not in str(raised.value)
    assert len(requests) == 1  # a refusal is not asked again


async def test_sefs_words_on_a_refusal_are_kept_up_to_a_limit() -> None:
    with pytest.raises(SefError) as raised:
        await sef(lambda _: httpx.Response(422, text="x" * 5000), []).send(DOCUMENT, REQUEST)

    assert raised.value.detail == "x" * SefClient.MAX_DETAIL


@pytest.mark.parametrize("status", [401, 403])
async def test_a_key_sef_refuses_is_unauthorized(status: int) -> None:
    requests: list[httpx.Request] = []

    with pytest.raises(SefError, match=rf"^SEF: unauthorized \({status}\)$") as raised:
        await sef(lambda _: httpx.Response(status, text="Invalid ApiKey"), requests).send(
            DOCUMENT, REQUEST
        )

    assert (raised.value.kind, raised.value.detail) == ("unauthorized", None)
    assert len(requests) == 1


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(200, text="<html>"),
        httpx.Response(200, json=[4711]),
        httpx.Response(200, json={"invoiceId": 815}),
        imported(salesInvoiceId=True),
        imported(salesInvoiceId=0),
        imported(salesInvoiceId="4711"),
        imported(invoiceId="815"),
        httpx.Response(204),
        httpx.Response(302, headers={"Location": "https://elsewhere.example"}),
    ],
    ids=[
        "not JSON",
        "not an object",
        "no sales invoice id",
        "a boolean id",
        "a zero id",
        "an id as text",
        "an invoice id as text",
        "no content",
        "a redirect",
    ],
)
async def test_an_answer_that_is_not_the_contracts_is_unreadable(answer: httpx.Response) -> None:
    with pytest.raises(SefError) as raised:
        await sef(lambda _: answer, []).send(DOCUMENT, REQUEST)

    assert raised.value.kind == "unreadable"


async def test_an_import_without_an_invoice_id_is_still_imported() -> None:
    result = await sef(lambda _: imported(invoiceId=None), []).send(DOCUMENT, REQUEST)

    assert result == Imported(sales_invoice_id=4711, invoice_id=None)


# --- where an invoice stands -------------------------------------------------------------------


async def test_an_invoice_is_asked_about_by_its_sales_invoice_id() -> None:
    requests: list[httpx.Request] = []

    standing = await sef(lambda _: invoice(), requests).standing(4711)

    assert standing == Standing(
        status=SefStatus.SENT,
        changed_at=datetime(2026, 11, 8, 20, 15, 3, 270000, tzinfo=UTC),
        comment=None,
    )
    (request,) = requests
    assert (request.method, request.url.path) == ("GET", "/api/publicApi/sales-invoice")
    assert dict(request.url.params) == {"invoiceId": "4711"}
    assert request.headers["ApiKey"] == "4711-4711-4711-4711"
    assert request.content == b""


async def test_a_buyers_decision_comes_with_its_comment_up_to_a_limit() -> None:
    standing = await sef(
        lambda _: invoice(status="Rejected", comment="Pogrešan iznos. " * 500), []
    ).standing(4711)

    assert standing.status is SefStatus.REJECTED
    assert standing.comment is not None
    assert len(standing.comment) == SefClient.MAX_DETAIL


@pytest.mark.parametrize(
    ("body", "changed_at"),
    [
        ({"lastModifiedUtc": "2026-11-08T20:15:03Z"}, datetime(2026, 11, 8, 20, 15, 3, tzinfo=UTC)),
        ({"lastModifiedUtc": "yesterday"}, None),
        ({"lastModifiedUtc": None}, None),
        ({"comment": ""}, None),
    ],
    ids=["with a zone", "not a time", "no time", "an empty comment"],
)
async def test_what_sef_leaves_out_or_garbles_is_none(
    body: dict[str, Any], changed_at: datetime | None
) -> None:
    standing = await sef(lambda _: invoice(**body), []).standing(4711)

    if "lastModifiedUtc" in body:
        assert standing.changed_at == changed_at
    else:
        assert standing.comment is None


@pytest.mark.parametrize("status", ["Lost", None, 3])
async def test_a_status_the_contract_does_not_name_is_unreadable(status: object) -> None:
    with pytest.raises(SefError) as raised:
        await sef(lambda _: invoice(status=status), []).standing(4711)

    assert raised.value.kind == "unreadable"


def test_an_invoice_is_final_once_its_buyer_decided_or_its_seller_undid_it() -> None:
    assert {
        SefStatus(status) for status in ("Approved", "Rejected", "Cancelled", "Storno", "Deleted")
    } == FINAL
    assert not FINAL & {SefStatus.NEW, SefStatus.SENDING, SefStatus.SENT, SefStatus.MISTAKE}


async def test_the_client_closes_its_connections() -> None:
    client = sef(lambda _: invoice(), [])

    await client.aclose()

    with pytest.raises(RuntimeError):
        await client.standing(4711)


def test_the_settings_name_sefs_demo_environment_by_its_origin() -> None:
    assert settings_for().sef_demo_base_url == "https://demoefaktura.mfin.gov.rs"
    chosen = settings_for(SEF_DEMO_BASE_URL="https://sef.example")
    assert chosen.sef_demo_base_url == "https://sef.example"
    for wrong in ("http://demoefaktura.mfin.gov.rs", "https://sef.example/api", "sef.example"):
        with pytest.raises(ValidationError):
            settings_for(SEF_DEMO_BASE_URL=wrong)
