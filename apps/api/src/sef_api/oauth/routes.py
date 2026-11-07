"""``/oauth``: the routes of the OAuth 2.1 authorization server (ADR-0044).

They answer once ``SEF_PUBLIC_URL`` names the API's address, which the server's documents and
tokens are issued from; before that, 404. Their errors are OAuth's (``error`` and
``error_description``), which the clients of the protocol read, rather than the API's.
"""

from __future__ import annotations

from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.auth.routes import NO_STORE, Problem
from sef_api.db import get_session
from sef_api.oauth import clients
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
        raise HTTPException(status.HTTP_404_NOT_FOUND, "this server has no authorization server")
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
