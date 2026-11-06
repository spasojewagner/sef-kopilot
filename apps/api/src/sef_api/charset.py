"""Every JSON answer says that it is UTF-8.

RFC 8259 defines no ``charset`` for ``application/json``: JSON exchanged between systems is
UTF-8, and a client that follows the RFC needs to be told nothing. Windows PowerShell 5.1 does
not follow it: ``Invoke-RestMethod`` reads a body without a ``charset`` as ISO-8859-1, so the
letters of a Serbian message or explanation (č, ć, š, ž, đ) come out as two characters each and
the model's quotation marks as control codes that a console acts on. Declaring the charset
changes nothing for any other client.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

__all__ = ["DeclareUTF8"]

_JSON = b"application/json"
_JSON_IN_UTF8 = b"application/json; charset=utf-8"


class DeclareUTF8:
    """ASGI middleware: an answer of type ``application/json`` is sent as
    ``application/json; charset=utf-8``. Other types keep what they say: the event streams
    already name their charset, and an XML document names its encoding itself."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def declaring(message: Message) -> None:
            if message["type"] == "http.response.start":
                message = {
                    **message,
                    "headers": [
                        (
                            name,
                            _JSON_IN_UTF8 if name == b"content-type" and value == _JSON else value,
                        )
                        for name, value in message.get("headers", ())
                    ],
                }
            await send(message)

        await self.app(scope, receive, declaring)
