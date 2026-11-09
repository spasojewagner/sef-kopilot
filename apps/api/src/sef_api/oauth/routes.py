"""``/oauth``: the routes of the OAuth 2.1 authorization server (ADR-0044).

They answer once ``SEF_PUBLIC_URL`` names the API's address, which the server's documents and
tokens are issued from; before that, 404. Their errors are OAuth's (``error`` and
``error_description``), which the clients of the protocol read, rather than the API's.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.auth.dependencies import (
    Principal,
    current_principal,
    current_role,
    get_token_settings,
    no_longer_active,
)
from sef_api.auth.routes import NO_STORE, Problem
from sef_api.auth.service import TokenSettings
from sef_api.db import get_session
from sef_api.logs import security_event
from sef_api.models import OAuthClient
from sef_api.oauth import authorization as authorizations
from sef_api.oauth import clients
from sef_api.oauth import tokens as oauth_tokens
from sef_api.oauth.authorization import AuthorizeError, UnredirectableError, issuer_of
from sef_api.oauth.clients import ClientMetadata, RegisteredClient
from sef_api.rate_limits import Counted, per_address
from sef_api.settings import Settings

__all__ = ["router"]

router = APIRouter(prefix="/oauth", tags=["oauth"])
Session = Annotated[AsyncSession, Depends(get_session)]


class RegistrationError(BaseModel):
    """Why a client could not register (RFC 7591 §3.2.2)."""

    error: Literal["invalid_redirect_uri", "invalid_client_metadata"]
    error_description: str


def require_authorization_server(request: Request) -> Settings:
    """The settings, when they name the API's address; 404 otherwise, since there is then no
    authorization server to speak of."""
    settings = cast(Settings, request.app.state.settings)
    if settings.public_url is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "this server has no authorization server",
            {"Cache-Control": "no-store"},
        )
    return settings


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=RegisteredClient,
    summary="Register an OAuth client",
    description=(
        "Dynamic client registration (RFC 7591), for an MCP client that connects for the first "
        "time. Every client is registered as public, `token_endpoint_auth_method: none`, "
        "whatever it asks for: it gets no secret, and proves with PKCE that it began the "
        "authorization it ends. A redirect URI is `https`, `http` on the loopback interface, "
        "or a scheme of the application's own; it has no fragment. Registering grants nothing: "
        "a person decides what the client may do when it first asks."
    ),
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": ClientMetadata.model_json_schema()}},
        }
    },
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": RegistrationError,
            "description": "The client's metadata or a redirect URI is not acceptable.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": Problem,
            "description": "This server has no authorization server (`SEF_PUBLIC_URL`).",
        },
        status.HTTP_429_TOO_MANY_REQUESTS: {
            "model": Problem,
            "description": "Too many registrations from this address; try again after "
            "`Retry-After` seconds.",
        },
    },
    dependencies=[
        NO_STORE,
        Depends(per_address(Counted.CLIENT_REGISTRATION)),
        Depends(require_authorization_server),
    ],
)
async def register_client(request: Request, session: Session) -> RegisteredClient | Response:
    try:
        metadata = ClientMetadata.model_validate(await request.json())
    except ValueError as error:  # not JSON, or not metadata (ValidationError is a ValueError)
        return _refused(error)
    return RegisteredClient.of(await clients.register(session, metadata))


def _refused(error: ValueError) -> JSONResponse:
    """The error a client is answered when its metadata will not do (RFC 7591 §3.2.2)."""
    if not isinstance(error, ValidationError):
        answer = RegistrationError(
            error="invalid_client_metadata", error_description="the body is no JSON object"
        )
    else:
        problems = error.errors()
        answer = RegistrationError(
            error=(
                "invalid_redirect_uri"
                if any(problem["loc"][:1] == ("redirect_uris",) for problem in problems)
                else "invalid_client_metadata"
            ),
            error_description="; ".join(
                f"{'.'.join(map(str, problem['loc'])) or 'the body'}: "
                f"{problem['msg'].removeprefix('Value error, ')}"
                for problem in problems
            ),
        )
    return JSONResponse(
        answer.model_dump(), status.HTTP_400_BAD_REQUEST, headers={"Cache-Control": "no-store"}
    )


async def in_person(
    principal: Annotated[Principal, Depends(current_principal)], session: Session
) -> Principal:
    """The caller, signed in with the role they hold now: a person, not an API key, since a
    person decides what a client may do for them."""
    if not principal.in_person:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "a person decides what a client may do: sign in to decide, an API key or an MCP "
            "client cannot",
        )
    role = await current_role(session, principal)
    if role is None:
        raise no_longer_active()
    return replace(principal, role=role)


InPerson = Annotated[Principal, Depends(in_person)]


class AuthorizationRequest(BaseModel):
    """What a client asks to do for the person deciding."""

    id: str
    client_id: str
    client_name: str | None = Field(description="The name the client registered, unchecked.")
    redirect_uri: str = Field(description="Where the person is sent back once they decide.")
    scopes: list[str] = Field(description="What the client asks to do, by scope.")
    withheld: list[str] = Field(
        description="Of those scopes, the ones the caller's role does not grant them in their "
        "organization: approving does not give them to the client."
    )
    expires_at: datetime = Field(description="Until when the request waits for a decision.")


class Decision(BaseModel):
    """Where to send the person once they have decided."""

    redirect_uri: str = Field(
        description="The client's redirect URI, with the code or the error `access_denied`, "
        "the client's state and this server's identifier (`iss`)."
    )


_GONE = HTTPException(
    status.HTTP_404_NOT_FOUND, "no such request waits for a decision: it expired or was decided"
)
_REQUESTS_RESPONSES: dict[int | str, dict[str, object]] = {
    status.HTTP_404_NOT_FOUND: {
        "model": Problem,
        "description": "No such request waits for a decision: it expired or was decided, or "
        "this server has no authorization server.",
    },
}


@router.get(
    "/authorize",
    summary="Ask a person to let a client act for them",
    description=(
        "The authorization endpoint (OAuth 2.1 §4.1), where an MCP client sends the person's "
        "browser. It requires `response_type=code`, PKCE (`code_challenge` with "
        "`code_challenge_method=S256`), a `redirect_uri` the client registered, the MCP "
        "endpoint as the `resource` (RFC 8707; the default) and scopes this server has "
        "(`invoices:validate`; the default). A request that will do is sent to the web "
        "application's page, where a signed-in person decides on it within ten minutes; one "
        "that will not is sent back to the client with an error, its state and this server's "
        "identifier (`iss`, RFC 9207). An unknown client or redirect URI is answered here."
    ),
    status_code=status.HTTP_302_FOUND,
    response_class=RedirectResponse,
    responses={
        status.HTTP_302_FOUND: {"description": "To the page where a person decides, or back."},
        status.HTTP_400_BAD_REQUEST: {
            "model": Problem,
            "description": "The client is not registered, or the redirect URI is not one it "
            "registered; or the client's metadata document, where documents are fetched, will "
            "not do.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": Problem,
            "description": "This server has no authorization server (`SEF_PUBLIC_URL`).",
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": Problem,
            "description": "This server has no page where a person decides (`SEF_WEB_URL`).",
        },
        status.HTTP_429_TOO_MANY_REQUESTS: {
            "model": Problem,
            "description": "Too many authorization requests from this address; try again after "
            "`Retry-After` seconds.",
        },
    },
    dependencies=[NO_STORE, Depends(per_address(Counted.AUTHORIZATION_REQUEST))],
)
async def authorize(
    request: Request,
    session: Session,
    settings: Annotated[Settings, Depends(require_authorization_server)],
) -> RedirectResponse:
    if settings.web_url is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "this server has no page where a person decides what a client may do",
        )
    try:
        asked = await authorizations.begin(
            session, settings, request.query_params, request.app.state.client_documents
        )
    except UnredirectableError as refused:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, refused.description) from None
    except AuthorizeError as refused:
        back = authorizations.redirect(
            refused.redirect_uri,
            error=refused.error,
            error_description=refused.description,
            state=refused.state,
            iss=issuer_of(settings),
        )
        return RedirectResponse(back, status.HTTP_302_FOUND, headers={"Cache-Control": "no-store"})
    page = authorizations.redirect(f"{settings.web_url}/oauth/consent", request=asked.id)
    return RedirectResponse(page, status.HTTP_302_FOUND, headers={"Cache-Control": "no-store"})


@router.get(
    "/requests/{request_id}",
    summary="Read a client's request",
    description=(
        "What the client asks to do, and what of it the caller's role does not grant, for the "
        "page where a signed-in person decides."
    ),
    responses=_REQUESTS_RESPONSES,
    dependencies=[NO_STORE, Depends(require_authorization_server)],
)
async def read_request(request_id: str, caller: InPerson, session: Session) -> AuthorizationRequest:
    # Anyone signed in may decide whether to let a client act for them, within their role.
    asked = await authorizations.pending(session, request_id)
    if asked is None:
        raise _GONE
    client = await session.get(OAuthClient, asked.client_id)
    return AuthorizationRequest(
        id=asked.id,
        client_id=asked.client_id,
        client_name=None if client is None else client.name,
        redirect_uri=asked.redirect_uri,
        scopes=list(asked.scopes),
        withheld=[scope for scope in asked.scopes if not caller.may(authorizations.SCOPES[scope])],
        expires_at=asked.expires_at,
    )


@router.post(
    "/requests/{request_id}/approval",
    summary="Let a client act for the caller",
    description=(
        "The caller lets the client do what it asked, within what their role grants them in "
        "their organization; the consent is recorded in the audit log. The answer is where to "
        "send the person: the client's redirect URI with a code, valid for two minutes."
    ),
    responses=_REQUESTS_RESPONSES
    | {
        status.HTTP_403_FORBIDDEN: {
            "model": Problem,
            "description": "An API key cannot decide, or the caller's role grants none of the "
            "scopes asked for.",
        }
    },
    dependencies=[NO_STORE],
)
async def approve_request(
    request_id: str,
    caller: InPerson,
    session: Session,
    settings: Annotated[Settings, Depends(require_authorization_server)],
) -> Decision:
    asked = await authorizations.pending(session, request_id)
    if asked is None:
        raise _GONE
    if not any(caller.may(authorizations.SCOPES[scope]) for scope in asked.scopes):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "your role grants none of the scopes the client asks for"
        )
    code = await authorizations.approve(session, asked, caller)
    if code is None:
        raise _GONE
    security_event(
        "oauth.consent-approved",
        user=str(caller.user_id),
        organization=str(caller.organization_id),
        client=asked.client_id,
        consent=asked.id,
    )
    return Decision(
        redirect_uri=authorizations.redirect(
            asked.redirect_uri, code=code, state=asked.state, iss=issuer_of(settings)
        )
    )


@router.post(
    "/requests/{request_id}/refusal",
    summary="Refuse a client's request",
    description=(
        "The caller does not let the client act for them. The answer is where to send the "
        "person: the client's redirect URI with the error `access_denied`."
    ),
    responses=_REQUESTS_RESPONSES,
    dependencies=[NO_STORE],
)
async def refuse_request(
    request_id: str,
    caller: InPerson,
    session: Session,
    settings: Annotated[Settings, Depends(require_authorization_server)],
) -> Decision:
    asked = await authorizations.pending(session, request_id)
    if asked is None or not await authorizations.refuse(session, asked):
        raise _GONE
    security_event(
        "oauth.consent-refused", user=str(caller.user_id), client=asked.client_id, consent=asked.id
    )
    return Decision(
        redirect_uri=authorizations.redirect(
            asked.redirect_uri,
            error="access_denied",
            error_description="the person did not let the client act for them",
            state=asked.state,
            iss=issuer_of(settings),
        )
    )


class TokenRequest(BaseModel):
    """A token request's parameters, sent as a form (RFC 6749 §3.2): those of a code's exchange
    or of a refresh, by its ``grant_type``."""

    grant_type: Literal["authorization_code", "refresh_token"]
    client_id: str = Field(description="The client's id, as it registered.")
    code: str | None = Field(None, description="The code a consent issued (`authorization_code`).")
    code_verifier: str | None = Field(
        None, description="The PKCE verifier whose S256 challenge began the authorization."
    )
    redirect_uri: str | None = Field(
        None,
        description="Where the code was sent; required unless the client registered one only.",
    )
    refresh_token: str | None = Field(None, description="The refresh token to spend.")
    scope: str | None = Field(
        None, description="On a refresh, fewer of the consent's scopes, separated by spaces."
    )
    resource: str | None = Field(
        None, description="The MCP endpoint, which the person consented to (RFC 8707)."
    )


class IssuedTokens(BaseModel):
    """An MCP client's tokens (RFC 6749 §5.1)."""

    access_token: str = Field(description="A JWT for the MCP endpoint alone (RFC 9068).")
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int = Field(description="Seconds until the access token expires.")
    refresh_token: str | None = Field(
        None,
        description="Good once: spending it issues the next one. Only for a client that "
        "registered the `refresh_token` grant.",
    )
    scope: str = Field(description="The scopes the access token carries, separated by spaces.")


class TokenErrorAnswer(BaseModel):
    """Why a token request will not do (RFC 6749 §5.2, RFC 8707 §2)."""

    error: Literal[
        "invalid_request",
        "invalid_grant",
        "invalid_scope",
        "invalid_target",
        "unauthorized_client",
        "unsupported_grant_type",
    ]
    error_description: str


_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


@router.post(
    "/token",
    summary="Exchange a code, or a refresh token, for tokens",
    description=(
        "The token endpoint (OAuth 2.1 §3.2), for public clients: the body is a form. "
        "`authorization_code` exchanges the code a consent issued, once, with the PKCE verifier "
        "that began it; `refresh_token` spends a refresh token for the next pair, with as many "
        "of the consent's scopes or fewer, for a client that registered that grant. The access "
        "token is for the MCP endpoint alone, for minutes; a code or a refresh token presented "
        "a second time revokes the consent. The scopes are those the person's role still allows."
    ),
    response_model=IssuedTokens,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/x-www-form-urlencoded": {"schema": TokenRequest.model_json_schema()}
            },
        }
    },
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": TokenErrorAnswer,
            "description": "The request, the code or the refresh token will not do.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": Problem,
            "description": "This server has no authorization server (`SEF_PUBLIC_URL`).",
        },
        status.HTTP_429_TOO_MANY_REQUESTS: {
            "model": Problem,
            "description": "Too many token requests from this address; try again after "
            "`Retry-After` seconds.",
        },
    },
    dependencies=[Depends(per_address(Counted.TOKEN_REQUEST))],
)
async def issue_tokens(
    request: Request,
    session: Session,
    settings: Annotated[Settings, Depends(require_authorization_server)],
    tokens: Annotated[TokenSettings, Depends(get_token_settings)],
) -> JSONResponse:
    try:
        form = oauth_tokens.form_of(await request.body(), request.headers.get("content-type"))
        grant = form.get("grant_type")
        if grant == "authorization_code":
            issued = await oauth_tokens.exchange_code(session, settings, tokens, form)
        elif grant == "refresh_token":
            issued = await oauth_tokens.refresh(session, settings, tokens, form)
        elif grant is None:
            raise oauth_tokens.TokenError("invalid_request", "the parameter grant_type is required")
        else:
            raise oauth_tokens.TokenError(
                "unsupported_grant_type", "the grant_type is authorization_code or refresh_token"
            )
    except oauth_tokens.TokenError as refused:
        answer = TokenErrorAnswer.model_validate(
            {"error": refused.error, "error_description": refused.description}
        )
        return JSONResponse(answer.model_dump(), status.HTTP_400_BAD_REQUEST, headers=_NO_STORE)
    return JSONResponse(
        IssuedTokens(
            access_token=issued.access_token,
            expires_in=issued.expires_in,
            refresh_token=issued.refresh_token,
            scope=" ".join(issued.scopes),
        ).model_dump(exclude_none=True),
        headers=_NO_STORE,
    )
