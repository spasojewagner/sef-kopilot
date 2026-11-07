"""Who may use the MCP endpoint (ADR-0042).

Until the server has an authorization server of its own (OAuth 2.1, the next step), the endpoint
takes the credential machine clients already have: an API key, sent as a bearer token. An access
token of the web application is refused, since it was issued for the API's routes and a token is
used only where it is meant to be. A request is checked as a route's is, the key and the role of
its member read again.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import replace
from typing import Final, cast

from fastapi import HTTPException, status
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from sef_api.api_keys import service as api_keys
from sef_api.auth.dependencies import Principal, current_role, invalid_key, no_longer_active
from sef_api.db import Database

__all__ = ["METHOD", "RequireKey"]

#: The one method the endpoint answers. Every message of the protocol is posted; the server has
#: no messages of its own to stream, so a GET that would open such a stream is refused.
METHOD: Final = "POST"

#: Where the endpoint leaves the caller for the tools, in the request's state.
_CALLER: Final = "mcp_caller"


class RequireKey:
    """ASGI middleware in front of the MCP endpoint. A page of an origin other than the web
    application's is refused (403), as a guard against DNS rebinding; a method other than POST
    too (405); and a request without a working API key (401, as the API's routes answer it).
    The others go on, with the key's principal in the request's state."""

    def __init__(self, app: ASGIApp, *, origins: Collection[str]) -> None:
        self.app = app
        self.origins = frozenset(origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Behind a route, which passes HTTP requests only.
        headers = Headers(scope=scope)
        try:
            origin = headers.get("origin")
            if origin is not None and origin not in self.origins:
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN, "requests from this origin are not accepted"
                )
            if scope["method"] != METHOD:
                raise HTTPException(
                    status.HTTP_405_METHOD_NOT_ALLOWED, "Method Not Allowed", {"Allow": METHOD}
                )
            database = cast(Database, scope["app"].state.database)
            caller = await _caller(database, headers.get("authorization"))
        except HTTPException as refused:
            answer = JSONResponse(
                {"detail": refused.detail}, refused.status_code, headers=refused.headers
            )
            await answer(scope, receive, send)
            return
        scope.setdefault("state", {})[_CALLER] = caller
        await self.app(scope, receive, send)


async def _caller(database: Database, authorization: str | None) -> Principal:
    """The principal of the request's API key, with the role its member holds now; the 401 the
    API's routes answer otherwise."""
    scheme, _, credential = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not credential:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "not signed in", {"WWW-Authenticate": "Bearer"}
        )
    if not api_keys.is_api_key(credential):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "the MCP endpoint takes an API key",
            {"WWW-Authenticate": 'Bearer error="invalid_token"'},
        )
    async with database.sessions() as session:
        holder = await api_keys.authenticate(session, credential)
        if holder is None:
            raise invalid_key()
        principal = Principal(holder.user_id, holder.organization_id, holder.role, holder.grant)
        role = await current_role(session, principal)
    if role is None:
        raise no_longer_active()
    return replace(principal, role=role)
