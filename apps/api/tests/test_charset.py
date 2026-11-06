"""Every JSON answer says that it is UTF-8; other answers keep the type they have."""

from __future__ import annotations

from httpx import AsyncClient
from starlette.types import Message, Receive, Scope, Send

from sef_api.charset import DeclareUTF8

JSON_IN_UTF8 = "application/json; charset=utf-8"


async def test_every_json_answer_says_it_is_utf8(client: AsyncClient) -> None:
    health = await client.get("/health")
    schema = await client.get("/openapi.json")
    refused = await client.get("/invoices")  # no token
    unknown = await client.get("/no/such/path")

    assert [answer.status_code for answer in (health, schema, refused, unknown)] == [
        200,
        200,
        401,
        404,
    ]
    assert {answer.headers["content-type"] for answer in (health, schema, refused, unknown)} == {
        JSON_IN_UTF8
    }


async def test_other_types_keep_what_they_say() -> None:
    sent: list[Message] = []

    async def document(_scope: Scope, _receive: Receive, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"application/xml"),
                    (b"x-described-as", b"application/json"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": b"<Invoice/>"})

    async def receive() -> Message:
        return {"type": "http.request"}

    async def send(message: Message) -> None:
        sent.append(message)

    await DeclareUTF8(document)({"type": "http"}, receive, send)

    assert sent[0]["headers"] == [
        (b"content-type", b"application/xml"),
        (b"x-described-as", b"application/json"),
    ]
    assert sent[1] == {"type": "http.response.body", "body": b"<Invoice/>"}


async def test_a_scope_that_is_not_http_passes_through() -> None:
    reached: list[Send] = []

    async def application(_scope: Scope, _receive: Receive, send: Send) -> None:
        reached.append(send)

    async def receive() -> Message:
        return {"type": "lifespan.startup"}

    async def send(_message: Message) -> None:
        pass

    await DeclareUTF8(application)({"type": "lifespan"}, receive, send)

    assert reached == [send]
