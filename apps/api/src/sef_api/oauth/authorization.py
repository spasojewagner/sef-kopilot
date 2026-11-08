"""A client's request to act for a person, the person's decision, and the code it issues
(OAuth 2.1 §4.1, ADR-0044).

``/oauth/authorize`` checks what a client asks before anyone is asked: a client it knows, a
redirect URI it registered, PKCE with S256, the MCP endpoint as the resource (RFC 8707) and the
scopes this server has. A request that passes waits, for ten minutes, for a signed-in person to
decide on the web application's page. Approved, it issues a code, valid for two minutes, for the
scopes the person's role grants; every answer sent back to the client names this server, the
issuer (RFC 9207).
"""

from __future__ import annotations

import hashlib
import re
import secrets
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Final
from urllib.parse import urlencode, urlsplit, urlunsplit

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api import audit
from sef_api.auth.dependencies import Principal
from sef_api.auth.permissions import Permission
from sef_api.models import AuditAction, OAuthAuthorization, OAuthClient
from sef_api.oauth import clients, documents
from sef_api.settings import Settings

__all__ = [
    "CODE_LIFETIME",
    "REQUEST_LIFETIME",
    "SCOPES",
    "AuthorizeError",
    "UnredirectableError",
    "approve",
    "begin",
    "canonical",
    "issuer_of",
    "pending",
    "redirect",
    "refuse",
    "resource_of",
]

#: The scopes a client may ask for, each the permission of the tools it allows: checking an
#: invoice, and storing invoices and reading the ones the person submitted. No scope reaches
#: every invoice of the organization (``invoices:manage``): an assistant sees its person's own.
SCOPES: Final[Mapping[str, Permission]] = MappingProxyType(
    {
        "invoices:validate": Permission.INVOICES_VALIDATE,
        "invoices:submit": Permission.INVOICES_SUBMIT,
    }
)
#: How long a request waits for a person's decision.
REQUEST_LIFETIME: Final = timedelta(minutes=10)
#: How long the code a consent issues may be exchanged.
CODE_LIFETIME: Final = timedelta(minutes=2)
#: An S256 challenge: the base64url of a SHA-256, without padding.
_CHALLENGE: Final = re.compile(r"[A-Za-z0-9_-]{43}")
#: The longest state a client may ask to have sent back.
MAX_STATE_LENGTH: Final = 500


@dataclass(frozen=True)
class UnredirectableError(Exception):
    """A request whose client or redirect URI is not known: answered where it was made, never
    sent to an address that nobody registered (OAuth 2.1 §4.1.2.1)."""

    description: str


@dataclass(frozen=True)
class AuthorizeError(Exception):
    """A request the client is sent back with an error (OAuth 2.1 §4.1.2.1)."""

    redirect_uri: str
    state: str | None
    error: str
    description: str


def issuer_of(settings: Settings) -> str:
    """This authorization server's identifier, the API's own origin."""
    if settings.public_url is None:
        raise RuntimeError("there is no authorization server without SEF_PUBLIC_URL")
    return settings.public_url


def resource_of(settings: Settings) -> str:
    """The canonical URI of the MCP endpoint, the one resource tokens are issued for."""
    return f"{issuer_of(settings)}/mcp"


def redirect(uri: str, **params: str | None) -> str:
    """``uri`` with ``params`` added to its query, those that are None left out."""
    parts = urlsplit(uri)
    added = urlencode({name: value for name, value in params.items() if value is not None})
    query = f"{parts.query}&{added}" if parts.query else added
    return urlunsplit(parts._replace(query=query))


def canonical(uri: str) -> str:
    """``uri`` with its scheme and host in lower case and no trailing slash, as resources are
    compared."""
    parts = urlsplit(uri)
    return urlunsplit(
        parts._replace(scheme=parts.scheme.lower(), netloc=parts.netloc.lower())
    ).rstrip("/")


#: Fetches the metadata document an ``https`` client_id names (ADR-0045).
DocumentFetcher = Callable[[str], Awaitable[documents.ClientDocument]]


async def _client(
    session: AsyncSession, client_id: str, fetch_document: DocumentFetcher | None
) -> OAuthClient | None:
    """The client ``client_id`` names: a registered one, or, where documents are fetched, the one
    its metadata document describes now; None for an unknown one."""
    if not documents.is_document_id(client_id):
        return await clients.find(session, client_id)
    if fetch_document is None:
        # Documents are not fetched here: a client once known by one is unknown now.
        return None
    try:
        document = await fetch_document(client_id)
    except documents.DocumentError as refused:
        raise UnredirectableError(str(refused)) from None
    return await clients.introduced(session, client_id, document)


async def begin(
    session: AsyncSession,
    settings: Settings,
    params: Mapping[str, str],
    fetch_document: DocumentFetcher | None = None,
) -> OAuthAuthorization:
    """The request the authorization's ``params`` make, kept for a person to decide on, and
    committed; :class:`UnredirectableError` or :class:`AuthorizeError` when it will not do. A
    client known by a metadata document is read from it with ``fetch_document``, if given."""
    client = await _client(session, params.get("client_id", ""), fetch_document)
    if client is None:
        raise UnredirectableError("no client is registered with this client_id")
    redirect_uri = params.get("redirect_uri")
    if redirect_uri is None and len(client.redirect_uris) == 1:
        redirect_uri = client.redirect_uris[0]
    if redirect_uri not in client.redirect_uris:
        raise UnredirectableError("the redirect_uri is not one the client registered")
    state = params.get("state")

    def refused(error: str, description: str) -> AuthorizeError:
        return AuthorizeError(redirect_uri, state, error, description)

    if params.get("response_type") != "code":
        raise refused("unsupported_response_type", "the response_type must be code")
    if params.get("code_challenge_method") != "S256":
        raise refused("invalid_request", "PKCE is required, with code_challenge_method S256")
    challenge = params.get("code_challenge", "")
    if not _CHALLENGE.fullmatch(challenge):
        raise refused("invalid_request", "the code_challenge is no S256 challenge")
    if state is not None and len(state) > MAX_STATE_LENGTH:
        raise refused("invalid_request", f"the state has more than {MAX_STATE_LENGTH} characters")
    try:
        resource = canonical(params.get("resource", resource_of(settings)))
    except ValueError:  # no URI at all
        resource = ""
    if resource != resource_of(settings):
        raise refused("invalid_target", "the resource is not this server's MCP endpoint")
    asked = params.get("scope", "").split() or list(SCOPES)
    if not set(asked) <= set(SCOPES):
        # Named in general: what the client sent is not repeated back (RFC 6749 §4.1.2.1).
        raise refused("invalid_scope", "a scope asked for is not one this server has")
    authorization = OAuthAuthorization(
        id=secrets.token_urlsafe(32),
        client_id=client.id,
        redirect_uri=redirect_uri,
        code_challenge=challenge,
        scopes=sorted(set(asked), key=list(SCOPES).index),
        resource=resource_of(settings),
        state=state,
        expires_at=datetime.now(UTC) + REQUEST_LIFETIME,
    )
    session.add(authorization)
    await session.commit()
    return authorization


async def pending(session: AsyncSession, request_id: str) -> OAuthAuthorization | None:
    """The request ``request_id``, while it waits for a decision."""
    authorization = await session.get(OAuthAuthorization, request_id)
    if (
        authorization is None
        or authorization.decision is not None
        or authorization.expires_at <= datetime.now(UTC)
    ):
        return None
    return authorization


async def approve(
    session: AsyncSession, authorization: OAuthAuthorization, caller: Principal
) -> str | None:
    """Approve the request for the scopes ``caller``'s role grants, recording the consent in the
    audit log, and commit; the code to send the client, or None when the request was decided
    meanwhile, or the role grants none of its scopes."""
    granted = [scope for scope in authorization.scopes if caller.may(SCOPES[scope])]
    if not granted:
        return None
    code = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    decided = await session.scalar(
        update(OAuthAuthorization)
        .where(
            OAuthAuthorization.id == authorization.id,
            OAuthAuthorization.decision.is_(None),
            OAuthAuthorization.expires_at > now,
        )
        .values(
            decision="approved",
            decided_at=now,
            organization_id=caller.organization_id,
            user_id=caller.user_id,
            scopes=granted,
            code_sha256=hashlib.sha256(code.encode()).hexdigest(),
            code_expires_at=now + CODE_LIFETIME,
        )
        .returning(OAuthAuthorization.id)
    )
    if decided is None:
        await session.rollback()
        return None
    audit.record(
        session,
        caller,
        AuditAction.OAUTH_CLIENT_AUTHORIZED,
        detail={"client_id": authorization.client_id, "scopes": granted},
    )
    await session.commit()
    return code


async def refuse(session: AsyncSession, authorization: OAuthAuthorization) -> bool:
    """Refuse the request, and commit; whether it was still waiting for a decision."""
    now = datetime.now(UTC)
    decided = await session.scalar(
        update(OAuthAuthorization)
        .where(
            OAuthAuthorization.id == authorization.id,
            OAuthAuthorization.decision.is_(None),
            OAuthAuthorization.expires_at > now,
        )
        .values(decision="refused", decided_at=now)
        .returning(OAuthAuthorization.id)
    )
    await session.commit()
    return decided is not None
