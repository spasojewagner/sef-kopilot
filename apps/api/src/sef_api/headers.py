"""The headers every answer of the API carries for the browser that may read it.

The API answers JSON, and a stored invoice's document as an attachment; it serves no page but its
interactive documentation, which only development has. So the browser is told to run, load and
frame nothing an answer holds (``Content-Security-Policy: default-src 'none'; frame-ancestors
'none'``), to take a type only as declared (``nosniff``), and to send no address of the API on
(``Referrer-Policy: no-referrer``): an answer opened in a tab, a document with markup in it say,
is inert. The documentation's pages, which load Swagger UI and ReDoc from a CDN, keep the first
header out; they exist outside production only (OWASP's REST Security Cheat Sheet; ASVS V3).
"""

from __future__ import annotations

from typing import Final

from starlette.types import ASGIApp, Message, Receive, Scope, Send

__all__ = ["DOCUMENTATION_PATHS", "SecureHeaders"]

#: The pages of the interactive documentation, which development serves.
DOCUMENTATION_PATHS: Final = frozenset({"/docs", "/docs/oauth2-redirect", "/redoc"})

_POLICY: Final = (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'")
_ALWAYS: Final = (
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
)


class SecureHeaders:
    """ASGI middleware: every HTTP answer carries :data:`_ALWAYS`, and the content security
    policy unless it serves a page of the documentation, where ``documented``. A header an
    answer already sets is kept as it is."""

    def __init__(self, app: ASGIApp, *, documented: bool) -> None:
        self.app = app
        self.documented = documented

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        page = self.documented and scope["path"] in DOCUMENTATION_PATHS
        added = _ALWAYS if page else (*_ALWAYS, _POLICY)

        async def securing(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", ()))
                present = {name.lower() for name, _value in headers}
                headers += [(name, value) for name, value in added if name not in present]
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, securing)
