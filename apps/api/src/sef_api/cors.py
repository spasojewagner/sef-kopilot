"""Cross-origin requests (CORS), two ways.

The pages of the web application's origins (``SEF_WEB_ORIGINS``) may call any route, with the
headers its requests carry. The pages of any origin may call the authorization server's public
endpoints, as an MCP client running in a browser does: its metadata documents, registration and
the token endpoint. None of these reads a cookie or answers with anything a page could not get
by asking for itself, so allowing every origin lends no page anyone else's authority.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Final

from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

__all__ = [
    "CORS_MAX_AGE_SECONDS",
    "CORS_METHODS",
    "CORS_REQUEST_HEADERS",
    "CORS_RESPONSE_HEADERS",
    "PUBLIC_REQUEST_HEADERS",
    "Cors",
]

#: What a page of the web application's origin may send: the methods the API answers, the
#: headers its requests carry (the token, the body's type, where an event stream stopped), and
#: the headers of an answer it may read (where a new resource is, how long to wait). No
#: credentials: a page sends its token in a header, never in a cookie.
CORS_METHODS: Final = ("GET", "POST", "PUT", "PATCH", "DELETE")
CORS_REQUEST_HEADERS: Final = ("Authorization", "Content-Type", "Last-Event-ID")
CORS_RESPONSE_HEADERS: Final = ("Location", "Retry-After")
#: What a page of any origin may send to the authorization server's public endpoints: a form or
#: JSON, and the protocol revision an MCP client names when it reads the metadata documents.
PUBLIC_REQUEST_HEADERS: Final = ("Content-Type", "MCP-Protocol-Version")
#: How long a browser may keep the answer to a preflight: ten minutes.
CORS_MAX_AGE_SECONDS: Final = 600


class Cors:
    """ASGI middleware that answers CORS for the web application's pages on every route, and for
    the pages of any origin on ``public_paths``; a preflight is answered before anything else
    runs, and every answer, an error included, carries the headers a page needs to read it."""

    def __init__(
        self, app: ASGIApp, *, web_origins: Collection[str], public_paths: Collection[str]
    ) -> None:
        self.public_paths = frozenset(public_paths)
        self.anyone = CORSMiddleware(
            app,
            allow_origins=["*"],
            allow_methods=["GET", "POST"],
            allow_headers=list(PUBLIC_REQUEST_HEADERS),
            expose_headers=["Retry-After"],
            max_age=CORS_MAX_AGE_SECONDS,
        )
        self.web: ASGIApp = (
            CORSMiddleware(
                app,
                allow_origins=list(web_origins),
                allow_methods=list(CORS_METHODS),
                allow_headers=list(CORS_REQUEST_HEADERS),
                expose_headers=list(CORS_RESPONSE_HEADERS),
                max_age=CORS_MAX_AGE_SECONDS,
            )
            if web_origins
            else app
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"] in self.public_paths:
            await self.anyone(scope, receive, send)
        else:
            await self.web(scope, receive, send)
