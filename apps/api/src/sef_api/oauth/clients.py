"""The clients of the OAuth 2.1 authorization server, registered by themselves (RFC 7591,
ADR-0044).

Every client is public: whatever authentication it asks for, it is registered with none
(``token_endpoint_auth_method: none``), as RFC 7591 lets a server substitute a value it
supports, and it proves with PKCE that it began the authorization it ends. Its redirect URIs are
those OAuth 2.1 allows: ``https``, ``http`` on the loopback interface for an application on the
person's own computer, or a scheme of the application's own.
"""

from __future__ import annotations

import secrets
from typing import Final, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.models import OAuthClient

__all__ = ["GRANT_TYPES", "ClientMetadata", "RegisteredClient", "find", "register"]

#: The grants a client may register for.
GRANT_TYPES: Final = ("authorization_code", "refresh_token")
#: The hosts an ``http`` redirect URI may name: the loopback interface.
LOOPBACK: Final = frozenset({"127.0.0.1", "[::1]", "localhost"})
#: Schemes that can do harm, or nothing, where a browser is sent.
REFUSED_SCHEMES: Final = frozenset({"javascript", "data", "file", "vbscript", "about", "blob"})
#: The longest redirect URI a client may register.
MAX_REDIRECT_URI_LENGTH: Final = 2000


class RedirectUriError(ValueError):
    """A redirect URI that no authorization may send a person to."""


def check_redirect_uri(uri: str) -> str:
    """``uri``, if an authorization may send a person back to it; :class:`RedirectUriError`
    otherwise."""
    if len(uri) > MAX_REDIRECT_URI_LENGTH:
        raise RedirectUriError(f"a redirect URI has at most {MAX_REDIRECT_URI_LENGTH} characters")
    parts = urlsplit(uri)
    if parts.fragment or "#" in uri:
        raise RedirectUriError(f"{uri} has a fragment")
    scheme = parts.scheme.lower()
    if not scheme:
        raise RedirectUriError(f"{uri} is not an absolute URI")
    if scheme in REFUSED_SCHEMES:
        raise RedirectUriError(f"{uri} uses a scheme no authorization sends a person to")
    if scheme in ("http", "https") and not parts.hostname:
        raise RedirectUriError(f"{uri} names no host")
    if scheme == "http" and parts.netloc.rsplit(":", 1)[0].lower() not in LOOPBACK:
        raise RedirectUriError(f"{uri} uses http, which only the loopback interface may")
    return uri


class ClientMetadata(BaseModel):
    """What a client says of itself when it registers (RFC 7591 §2); what this server does not
    use is ignored."""

    model_config = ConfigDict(extra="ignore")

    redirect_uris: list[str] = Field(min_length=1, max_length=10)
    client_name: str | None = Field(default=None, min_length=1, max_length=100)
    grant_types: list[str] = Field(default_factory=lambda: ["authorization_code"])
    response_types: list[str] = Field(default_factory=lambda: ["code"])
    token_endpoint_auth_method: str | None = None

    @field_validator("redirect_uris")
    @classmethod
    def _check_redirect_uris(cls, uris: list[str]) -> list[str]:
        return [check_redirect_uri(uri) for uri in uris]

    @field_validator("grant_types")
    @classmethod
    def _check_grant_types(cls, grants: list[str]) -> list[str]:
        if "authorization_code" not in grants:
            raise ValueError("grant_types must include authorization_code")
        unknown = sorted(set(grants) - set(GRANT_TYPES))
        if unknown:
            raise ValueError(f"grant_types holds {', '.join(unknown)}, which this server has not")
        return sorted(set(grants), key=GRANT_TYPES.index)

    @field_validator("response_types")
    @classmethod
    def _check_response_types(cls, types: list[str]) -> list[str]:
        if set(types) != {"code"}:
            raise ValueError("response_types must be code alone")
        return ["code"]


class RegisteredClient(BaseModel):
    """What a client is told it is registered as (RFC 7591 §3.2.1)."""

    client_id: str
    client_id_issued_at: int = Field(description="When it was registered, in Unix seconds.")
    client_name: str | None
    redirect_uris: list[str]
    grant_types: list[str]
    response_types: list[Literal["code"]] = Field(default=["code"])
    token_endpoint_auth_method: Literal["none"] = Field(
        default="none", description="Every client is public, and proves itself with PKCE."
    )

    @classmethod
    def of(cls, client: OAuthClient) -> RegisteredClient:
        return cls(
            client_id=client.id,
            client_id_issued_at=int(client.created_at.timestamp()),
            client_name=client.name,
            redirect_uris=list(client.redirect_uris),
            grant_types=list(client.grant_types),
        )


async def register(session: AsyncSession, metadata: ClientMetadata) -> OAuthClient:
    """Register a public client as ``metadata`` describes it, and commit."""
    client = OAuthClient(
        id=secrets.token_urlsafe(24),
        name=metadata.client_name,
        redirect_uris=metadata.redirect_uris,
        grant_types=metadata.grant_types,
    )
    session.add(client)
    await session.commit()
    return client


async def find(session: AsyncSession, client_id: str) -> OAuthClient | None:
    """The client registered as ``client_id``, if any."""
    return await session.get(OAuthClient, client_id)
