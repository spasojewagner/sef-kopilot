"""Who may use the MCP endpoint, and what each tool asks of the caller (ADR-0042, ADR-0044).

The endpoint takes two credentials, as a bearer token: an API key, which a machine client is
given, and, once the server is an authorization server (``SEF_PUBLIC_URL``), an access token its
token endpoint issued for this endpoint, for the scopes a person consented to. The web
application's access token is refused, since it was issued for the API's routes and a token is
used only where it is meant to be. A request is checked as a route's is: the key, or the
consent behind the token, and the role of the member are read again; each tool then checks the
permission it needs, which an access token's scopes must allow too.

A request without a credential, or with one that will not do, is answered 401 with a challenge
that names the protected resource's metadata (RFC 9728 §5.1) and the scopes, so that a client
that has never met the server knows where to sign its person in. A call through an MCP client of
a tool its scopes do not reach, which the person's role would allow, is answered 403
``insufficient_scope`` with the scopes to ask for, so that the client asks its person again
(ADR-0046); the tool itself never runs for it.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import replace
from types import MappingProxyType
from typing import Final, cast

from fastapi import HTTPException, status
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from sef_api.api_keys import service as api_keys
from sef_api.auth.dependencies import (
    Consent,
    Principal,
    consent_stands,
    current_role,
    invalid_key,
    no_longer_active,
    revoked_consent,
)
from sef_api.auth.permissions import ROLE_PERMISSIONS, Permission
from sef_api.auth.service import TokenSettings
from sef_api.db import Database
from sef_api.logs import security_event
from sef_api.models import Role
from sef_api.oauth import authorization as authorizations
from sef_api.oauth import tokens as oauth_tokens
from sef_api.oauth.authorization import issuer_of, resource_of
from sef_api.oauth.metadata import METADATA_PATH
from sef_api.rate_limits import client_address
from sef_api.settings import Settings

__all__ = ["METHOD", "RequireCredential", "admitted", "as_tool_errors", "challenge"]

#: The one method the endpoint answers. Every message of the protocol is posted; the server has
#: no messages of its own to stream, so a GET that would open such a stream is refused.
METHOD: Final = "POST"

#: Where the endpoint leaves the caller for the tools, in the request's state.
_CALLER: Final = "mcp_caller"


class RequireCredential:
    """ASGI middleware in front of the MCP endpoint. A page of an origin other than the web
    application's is refused (403), as a guard against DNS rebinding; a method other than POST
    too (405); a request without a working credential (401, with its challenge); and a call
    through an MCP client of a tool its scopes do not reach (403, with the scopes to ask for).
    The others go on, with the caller's principal in the request's state. ``permissions`` is
    what each tool needs, by its name."""

    def __init__(
        self, app: ASGIApp, *, origins: Collection[str], permissions: Mapping[str, Permission]
    ) -> None:
        self.app = app
        self.origins = frozenset(origins)
        self.permissions = MappingProxyType(dict(permissions))

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
            state = scope["app"].state
            settings = cast(Settings, state.settings)
            caller = await _caller(
                cast(Database, state.database),
                settings,
                cast(TokenSettings, state.tokens),
                headers.get("authorization"),
                Request(scope),
            )
            if caller.scopes is not None:
                body, receive = await _buffered(receive)
                lacking = _beyond_scopes(body, caller, self.permissions)
                if lacking:
                    raise _step_up(settings, caller, lacking)
        except HTTPException as refused:
            answer = JSONResponse(
                {"detail": refused.detail}, refused.status_code, headers=refused.headers
            )
            await answer(scope, receive, send)
            return
        scope.setdefault("state", {})[_CALLER] = caller
        await self.app(scope, receive, send)


def challenge(
    settings: Settings, error: str | None = None, scopes: Collection[str] | None = None
) -> str:
    """The ``WWW-Authenticate`` of a refusal: with an authorization server, where the endpoint's
    metadata is and the scopes to ask for, those a client asks for first unless ``scopes`` are
    named (RFC 9728 §5.1, RFC 6750 §3)."""
    parameters = [] if error is None else [f'error="{error}"']
    if settings.public_url is not None:
        asked = authorizations.DEFAULT_SCOPES if scopes is None else scopes
        parameters += [
            f'resource_metadata="{issuer_of(settings)}{METADATA_PATH}"',
            f'scope="{" ".join(asked)}"',
        ]
    return " ".join(["Bearer", ", ".join(parameters)]).strip()


async def _buffered(receive: Receive) -> tuple[bytes, Receive]:
    """The request's body, read whole, and a ``receive`` that gives it to the server again. The
    API's limit on bodies has already bounded it (``SEF_MAX_BODY_BYTES``)."""
    body = bytearray()
    while True:
        message = await receive()
        if message["type"] != "http.request":
            # The client went away: the server learns it as it would have.
            pending: list[Message] = [message]
            break
        body += message.get("body", b"")
        if not message.get("more_body", False):
            pending = [{"type": "http.request", "body": bytes(body), "more_body": False}]
            break

    async def replay() -> Message:
        return pending.pop() if pending else await receive()

    return bytes(body), replay


def _beyond_scopes(
    body: bytes, caller: Principal, permissions: Mapping[str, Permission]
) -> list[Permission]:
    """The permissions of the tools the posted messages call that the caller's role grants, a
    scope could allow, and their client's scopes do not: what asking the person again could
    allow. Anything else, a message that is no JSON included, is the server's to answer."""
    try:
        posted = json.loads(body)
    except ValueError:
        return []
    granted = ROLE_PERMISSIONS[caller.role]
    allowed = caller.scopes or frozenset()
    lacking: list[Permission] = []
    # A client of the protocol's revision 2025-03-26 may post a batch of messages.
    for message in posted if isinstance(posted, list) else [posted]:
        if not isinstance(message, dict) or message.get("method") != "tools/call":
            continue
        params = message.get("params")
        name = params.get("name") if isinstance(params, dict) else None
        permission = permissions.get(name) if isinstance(name, str) else None
        if (
            permission is not None
            and permission in granted
            and permission in _SCOPE_OF
            and permission not in allowed
        ):
            lacking.append(permission)
    return lacking


#: The scope that allows each permission a scope allows.
_SCOPE_OF: Final[Mapping[Permission, str]] = MappingProxyType(
    {permission: scope for scope, permission in authorizations.SCOPES.items()}
)


def _step_up(
    settings: Settings, caller: Principal, lacking: Collection[Permission]
) -> HTTPException:
    """A 403 that asks the client to ask its person again, for the scopes it holds and those the
    tools it called need: a client need not remember what it was allowed before (ADR-0046)."""
    allowed = caller.scopes or frozenset()
    scopes = [
        scope
        for scope, permission in authorizations.SCOPES.items()
        if permission in allowed or permission in lacking
    ]
    needed = " ".join(_SCOPE_OF[permission] for permission in dict.fromkeys(lacking))
    return HTTPException(
        status.HTTP_403_FORBIDDEN,
        f"a call needs {needed}, which the person has not allowed this client",
        {"WWW-Authenticate": challenge(settings, "insufficient_scope", scopes)},
    )


#: Why an access token that will not do is refused, whatever the reason: whether its person left
#: or was deactivated is not the client's to know, as the token endpoint does not tell it either.
_NOT_ADMITTED: Final = "invalid or expired access token"


def _refused(settings: Settings, detail: str, error: str | None = "invalid_token") -> HTTPException:
    """A 401 that names where to get a credential that will do: every refusal of the endpoint's
    carries its challenge, with ``invalid_token`` for a credential that came and will not do."""
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail, {"WWW-Authenticate": challenge(settings, error)}
    )


async def _caller(
    database: Database,
    settings: Settings,
    tokens: TokenSettings,
    authorization: str | None,
    request: Request,
) -> Principal:
    """The principal of the request's API key or access token, with the role its member holds
    now; a 401 in the API's words otherwise, with the endpoint's challenge."""
    scheme, _, credential = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not credential:
        raise _refused(settings, "not signed in", error=None)
    by_key = api_keys.is_api_key(credential)
    if not by_key and settings.public_url is None:
        raise _refused(settings, "the MCP endpoint takes an API key")
    async with database.sessions() as session:
        if by_key:
            principal = await _key_holder(session, settings, credential, request)
        else:
            principal = await _token_holder(session, settings, tokens, credential)
        role = await current_role(session, principal)
    if role is None:
        # A machine client of the member's own is told why, as the routes tell it; an assistant
        # the member let act for them is not.
        raise _refused(settings, str(no_longer_active().detail) if by_key else _NOT_ADMITTED)
    return replace(principal, role=role)


async def _key_holder(
    session: AsyncSession, settings: Settings, credential: str, request: Request
) -> Principal:
    """The principal of an API key, as it was issued; a 401 for one that does not work."""
    holder = await api_keys.authenticate(session, credential)
    if holder is None:
        security_event("api-key.refused", address=client_address(request))
        raise _refused(settings, str(invalid_key().detail))
    return Principal(holder.user_id, holder.organization_id, holder.role, holder.grant)


async def _token_holder(
    session: AsyncSession, settings: Settings, tokens: TokenSettings, credential: str
) -> Principal:
    """The principal of an access token the token endpoint issued for this endpoint, allowed
    what its scopes allow; a 401 for one that will not do, or whose consent was revoked or is
    gone (a code or a refresh token presented twice, or a member who left)."""
    try:
        claims = oauth_tokens.decode_access_token(
            credential,
            issuer=issuer_of(settings),
            audience=resource_of(settings),
            secret=tokens.secret,
        )
    except oauth_tokens.InvalidTokenError:
        raise _refused(settings, _NOT_ADMITTED) from None
    allowed = frozenset(
        authorizations.SCOPES[scope] for scope in claims.scopes if scope in authorizations.SCOPES
    )
    # The role is the member's as it is now, read with the API key's (see ``_caller``).
    principal = Principal(
        claims.user_id,
        claims.organization_id,
        Role.CLIENT,
        scopes=allowed,
        consent=Consent(claims.authorization_id, claims.client_id),
    )
    # A token is its consent's, while it stands: the person, their organization and the client
    # it names.
    if not await consent_stands(session, principal):
        raise _refused(settings, str(revoked_consent().detail))
    return principal


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
