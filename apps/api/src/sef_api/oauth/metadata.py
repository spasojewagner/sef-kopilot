"""The documents that send an MCP client to the authorization server (ADR-0044).

A client is given one address, the MCP endpoint's. Refused there, it reads where the endpoint's
protected resource metadata is (RFC 9728), which names the authorization server; that server's
metadata (RFC 8414) names its endpoints and what it supports. Both are public, and a page of
any origin may read them; they answer once ``SEF_PUBLIC_URL`` makes the API an authorization
server.
"""

from __future__ import annotations

from typing import Annotated, Final, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from sef_api.auth.routes import Problem
from sef_api.oauth import authorization as authorizations
from sef_api.oauth.authorization import issuer_of, resource_of
from sef_api.oauth.routes import require_authorization_server
from sef_api.settings import Settings

__all__ = ["METADATA_PATH", "router"]

router = APIRouter(tags=["oauth"])

#: Where the MCP endpoint's protected resource metadata is (RFC 9728 §3.1): the well-known path,
#: followed by the endpoint's own.
METADATA_PATH: Final = "/.well-known/oauth-protected-resource/mcp"

#: Public documents: a page of any origin may read them with a plain GET, as a client in a
#: browser does. A request a browser asks about first, for headers of its client's own, is the
#: API's CORS settings' to answer, as are the other endpoints of the authorization server.
_ANYONE: Final = {"Access-Control-Allow-Origin": "*"}
_NOT_HERE: Final[dict[int | str, dict[str, object]]] = {
    404: {"model": Problem, "description": "This server has no authorization server."}
}


class ProtectedResource(BaseModel):
    """The MCP endpoint, as a protected resource (RFC 9728 §2)."""

    resource: str = Field(description="The MCP endpoint, the audience of its access tokens.")
    authorization_servers: list[str] = Field(description="The issuer of its access tokens.")
    scopes_supported: list[str]
    bearer_methods_supported: list[Literal["header"]] = ["header"]
    resource_name: str = "SEF Kopilot"


class AuthorizationServer(BaseModel):
    """The authorization server, as RFC 8414 §2 describes it."""

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str
    scopes_supported: list[str]
    response_types_supported: list[Literal["code"]] = ["code"]
    grant_types_supported: list[str] = ["authorization_code", "refresh_token"]
    token_endpoint_auth_methods_supported: list[Literal["none"]] = Field(
        default=["none"], description="Every client is public, and proves itself with PKCE."
    )
    code_challenge_methods_supported: list[Literal["S256"]] = ["S256"]
    authorization_response_iss_parameter_supported: bool = Field(
        default=True, description="Every answer to the client names the issuer (RFC 9207)."
    )
    client_id_metadata_document_supported: bool = Field(
        description=(
            "Whether a client may be known by an `https` client_id whose metadata document this "
            "server fetches (ADR-0045)."
        )
    )


Server = Annotated[Settings, Depends(require_authorization_server)]


def _protected_resource(settings: Settings) -> ProtectedResource:
    return ProtectedResource(
        resource=resource_of(settings),
        authorization_servers=[issuer_of(settings)],
        scopes_supported=list(authorizations.SCOPES),
    )


@router.get(
    METADATA_PATH,
    summary="The MCP endpoint's protected resource metadata",
    description=(
        "Where a client refused at `/mcp` learns who issues the endpoint's access tokens "
        "(RFC 9728); the endpoint's `WWW-Authenticate` names this address."
    ),
    responses=_NOT_HERE,
)
def protected_resource(settings: Server, response: Response) -> ProtectedResource:
    response.headers.update(_ANYONE)
    return _protected_resource(settings)


@router.get(
    "/.well-known/oauth-protected-resource",
    summary="The API's protected resource metadata",
    description=(
        "The same document at the address a client tries when it was not told the endpoint's "
        "own: the MCP endpoint is the API's one protected resource."
    ),
    responses=_NOT_HERE,
)
def protected_resource_at_the_root(settings: Server, response: Response) -> ProtectedResource:
    # RFC 9728 §3.3 would have the document at this address name the API's origin, from which
    # the address is made. It names the MCP endpoint all the same: an MCP client takes a resource
    # that its server's address begins with and asks for a token for it, and a token for the
    # origin, which the authorization server refuses, would be of no use at the endpoint.
    response.headers.update(_ANYONE)
    return _protected_resource(settings)


@router.get(
    "/.well-known/oauth-authorization-server",
    summary="The authorization server's metadata",
    description=(
        "The authorization server's endpoints and what they support (RFC 8414): public "
        "clients registering themselves, codes with PKCE (S256), refresh tokens, the issuer in "
        "every answer."
    ),
    responses=_NOT_HERE,
)
def authorization_server(settings: Server, response: Response) -> AuthorizationServer:
    response.headers.update(_ANYONE)
    issuer = issuer_of(settings)
    return AuthorizationServer(
        issuer=issuer,
        authorization_endpoint=f"{issuer}/oauth/authorize",
        token_endpoint=f"{issuer}/oauth/token",
        registration_endpoint=f"{issuer}/oauth/register",
        scopes_supported=list(authorizations.SCOPES),
        client_id_metadata_document_supported=settings.client_metadata_documents,
    )
