"""Request bodies other than invoices are bounded before the application reads them."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from starlette.types import Message

from sef_api.bodies import LimitBodies
from sef_api.charset import DeclareUTF8
from sef_api.main import create_app

from .conftest import settings_for

LIMIT = 100


def echoing() -> FastAPI:
    """An application that answers with the length of the body it read, behind the limit."""
    app = FastAPI()

    @app.post("/echo")
    async def echo(request: Request) -> dict[str, int]:
        return {"read": len(await request.body())}

    app.add_middleware(LimitBodies, limit=LIMIT)
    app.add_middleware(DeclareUTF8)
    return app


@pytest.fixture
async def http() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=echoing()), base_url="http://test") as c:
        yield c


async def chunks(*parts: bytes) -> AsyncIterator[bytes]:
    for part in parts:
        yield part


async def test_a_body_within_the_limit_reaches_the_application_whole(http: AsyncClient) -> None:
    answer = await http.post("/echo", content=b"x" * LIMIT, headers={"content-type": "text/plain"})

    assert (answer.status_code, answer.json()) == (200, {"read": LIMIT})


async def test_a_body_sent_in_chunks_is_put_together(http: AsyncClient) -> None:
    answer = await http.post("/echo", content=chunks(b"{", b"}" * 9))

    assert (answer.status_code, answer.json()) == (200, {"read": 10})


async def test_a_declared_length_over_the_limit_is_refused_before_anything_is_read(
    http: AsyncClient,
) -> None:
    answer = await http.post("/echo", json={"padding": "x" * LIMIT})

    assert answer.status_code == 413
    assert answer.json() == {"detail": f"the request body is larger than {LIMIT} bytes"}
    assert answer.headers["content-type"] == "application/json; charset=utf-8"


async def test_a_longer_body_without_a_declared_length_is_refused_while_it_is_read(
    http: AsyncClient,
) -> None:
    answer = await http.post("/echo", content=chunks(b"x" * 60, b"x" * 60, b"never read"))

    assert answer.status_code == 413


async def test_an_invoice_is_left_to_the_limit_of_its_own(http: AsyncClient) -> None:
    answer = await http.post(
        "/echo", content=b"<x/>" * LIMIT, headers={"content-type": "application/xml; charset=utf-8"}
    )

    assert (answer.status_code, answer.json()) == (200, {"read": 4 * LIMIT})


async def test_a_request_without_a_body_passes(http: AsyncClient) -> None:
    answer = await http.post("/echo")

    assert (answer.status_code, answer.json()) == (200, {"read": 0})


async def test_the_api_bounds_the_json_it_is_sent() -> None:
    app = create_app(settings_for(SEF_MAX_BODY_BYTES="65536"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        answer = await client.post("/auth/login", json={"email": "x" * 70_000, "password": "x"})
    await app.state.database.engine.dispose()

    assert answer.status_code == 413


async def test_a_client_that_goes_away_while_sending_is_not_answered() -> None:
    reached: list[str] = []
    sent: list[object] = []

    async def application(*_args: object) -> None:
        reached.append("the application")

    async def receive() -> dict[str, object]:
        return {"type": "http.disconnect"}

    async def send(message: object) -> None:
        sent.append(message)

    scope = {"type": "http", "headers": [(b"content-type", b"application/json")]}
    await LimitBodies(application, limit=LIMIT)(scope, receive, send)

    assert (reached, sent) == ([], [])


async def test_a_declared_length_over_the_limit_reads_none_of_the_body() -> None:
    received: list[str] = []
    sent: list[Message] = []

    async def application(*_args: object) -> None:
        raise AssertionError("the application was reached")

    async def receive() -> Message:
        received.append("read")
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    headers = [(b"content-type", b"application/json"), (b"content-length", b"101")]
    await LimitBodies(application, limit=LIMIT)({"type": "http", "headers": headers}, receive, send)

    assert received == []
    assert sent[0]["status"] == 413
