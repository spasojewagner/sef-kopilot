"""Every request body that is not an invoice is bounded: a client cannot make the API hold
more of it in memory than the limit.

FastAPI reads a JSON body whole before it validates it, however long it is. An invoice, and a
PDF or a picture to read one from, is read by :mod:`sef_api.invoices.upload`, in chunks, within
a limit of its own; every other body (the JSON of a sign-in, an invitation, a list of patches)
passes through :class:`LimitBodies` first, which reads it up to the limit and hands it on, or
answers 413 as soon as the body is longer, whether or not the client declared its length.
"""

from __future__ import annotations

import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from sef_api.invoices.upload import UPLOAD_MEDIA_TYPES

__all__ = ["LimitBodies"]


def _header(scope: Scope, name: bytes) -> str:
    for key, value in scope.get("headers", ()):
        if key == name:
            return str(value.decode("latin-1"))
    return ""


class LimitBodies:
    """ASGI middleware: a request body that is not an invoice, or a document to read one from,
    may be at most ``limit`` bytes long; a longer one is answered with 413 before the
    application sees the request."""

    def __init__(self, app: ASGIApp, *, limit: int) -> None:
        self.app = app
        self.limit = limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        media_type = _header(scope, b"content-type").split(";", 1)[0].strip().lower()
        if scope["type"] != "http" or media_type in UPLOAD_MEDIA_TYPES:
            await self.app(scope, receive, send)
            return
        declared = _header(scope, b"content-length")
        if declared.isdigit() and int(declared) > self.limit:
            await self._refuse(send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] != "http.request":  # the client went away
                return
            body += message.get("body", b"")
            if len(body) > self.limit:
                await self._refuse(send)
                return
            if not message.get("more_body", False):
                break
        whole: list[Message] = [{"type": "http.request", "body": bytes(body), "more_body": False}]

        async def replay() -> Message:
            return whole.pop() if whole else await receive()

        await self.app(scope, replay, send)

    async def _refuse(self, send: Send) -> None:
        detail = {"detail": f"the request body is larger than {self.limit} bytes"}
        content = json.dumps(detail).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(content)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": content})
