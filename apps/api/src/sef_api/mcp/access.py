"""Who may use the MCP endpoint, and what each tool asks of the caller (ADR-0042).

Until the server has an authorization server of its own (OAuth 2.1, the next step), the endpoint
takes the credential machine clients already have: an API key, sent as a bearer token. An access
token of the web application is refused, since it was issued for the API's routes and a token is
used only where it is meant to be. A request is checked as a route's is, the key and the role of
its member read again; each tool then checks the permission it needs.
"""

from __future__ import annotations

from collections.abc import Collection, Iterator
from contextlib import contextmanager
from dataclasses import replace
from typing import Final, cast

from fastapi import HTTPException, status
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from sef_api.api_keys import service as api_keys
from sef_api.auth.dependencies import Principal, current_role, invalid_key, no_longer_active
from sef_api.auth.permissions import Permission
from sef_api.db import Database

__all__ = ["METHOD", "RequireKey", "admitted", "as_tool_errors"]

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


def admitted(context: Context, permission: Permission) -> tuple[Request, Principal]:
    """The request a tool answers and its caller, when the caller may do what ``permission``
    allows; a tool error that names the permission otherwise."""
    request = context.request_context.request
    if not isinstance(request, Request):
        raise RuntimeError("a tool of the MCP server runs only behind the endpoint at /mcp")
    caller = cast(Principal, getattr(request.state, _CALLER))
    if not caller.may(permission):
        raise ToolError(f"requires the permission {permission}")
    return request, caller


@contextmanager
def as_tool_errors() -> Iterator[None]:
    """What the API's routes would answer with an HTTP error becomes the tool's error, in the
    same words: why, and when to try again."""
    try:
        yield
    except HTTPException as error:
        raise ToolError(str(error.detail)) from None
