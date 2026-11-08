"""The tokens a consent issues to an MCP client: a code exchanged for them, and a refresh token
for new ones (OAuth 2.1 §4.1.3 and §4.3, ADR-0044).

An access token is a JWT for the MCP endpoint alone (RFC 9068): issued by this server (``iss``)
for the resource the person consented to (``aud``), naming the person (``sub``), their
organization, the client, the scopes and the consent (``sid``), for minutes. It is signed with a
key of its own, derived from the API's, so that it cannot pass for the web application's access
token, nor theirs for it, even where a check were missed. A refresh token is opaque, kept as its
SHA-256, spent once and replaced, to a client that registered the ``refresh_token`` grant. One
presented again, or a code presented twice, means someone else holds a copy: the consent is
revoked. Its refresh tokens are refused from then on, and its access tokens at the MCP endpoint,
which reads the consent on every request.

The person's role is read again at every exchange: a token carries the scopes the consent
granted that the role still allows, and a role that allows none of them gets no token.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final
from urllib.parse import parse_qsl

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.auth.permissions import ROLE_PERMISSIONS
from sef_api.auth.service import TokenSettings
from sef_api.auth.tokens import new_opaque_token, opaque_token_digest
from sef_api.logs import security_event
from sef_api.models import (
    Membership,
    OAuthAuthorization,
    OAuthClient,
    OAuthRefreshToken,
    Role,
    User,
)
from sef_api.oauth import authorization as authorizations
from sef_api.oauth.authorization import canonical, issuer_of, resource_of
from sef_api.settings import Settings

__all__ = [
    "AccessClaims",
    "InvalidTokenError",
    "Issued",
    "TokenError",
    "decode_access_token",
    "exchange_code",
    "form_of",
    "issue_access_token",
    "refresh",
]

ALGORITHM: Final = "HS256"
#: The header type of an access token in JWT form (RFC 9068).
TOKEN_TYPE: Final = "at+jwt"
#: The grant a client registers to be given refresh tokens (RFC 7591 §2).
REFRESH_GRANT: Final = "refresh_token"
_REQUIRED: Final = ("iss", "aud", "sub", "org", "client_id", "scope", "sid", "iat", "exp", "jti")
#: What the signing key of these tokens is derived for, from the API's own key.
_PURPOSE: Final = b"sef-kopilot: the MCP endpoint's access tokens"
#: A PKCE verifier: 43 to 128 unreserved characters (RFC 7636 §4.1).
_VERIFIER: Final = re.compile(r"[A-Za-z0-9._~-]{43,128}")
#: More parameters than any token request has.
_MOST_PARAMETERS: Final = 20

InvalidTokenError = jwt.InvalidTokenError


@dataclass(frozen=True)
class TokenError(Exception):
    """A token request that will not do, as OAuth answers it (RFC 6749 §5.2, RFC 8707 §2)."""

    error: str
    description: str


@dataclass(frozen=True)
class Issued:
    """What the client is answered: its tokens, and the scopes they carry."""

    access_token: str
    expires_in: int
    #: None for a client that did not register the ``refresh_token`` grant.
    refresh_token: str | None
    scopes: list[str]


@dataclass(frozen=True)
class AccessClaims:
    """What an access token of the MCP endpoint asserts."""

    user_id: uuid.UUID
    organization_id: uuid.UUID
    client_id: str
    scopes: tuple[str, ...]
    #: The consent the token was issued for.
    authorization_id: str
    expires_at: datetime


def _key(secret: str) -> bytes:
    """The key these tokens are signed with: one of their own, from the API's signing key."""
    return hmac.new(secret.encode(), _PURPOSE, hashlib.sha256).digest()


def issue_access_token(
    authorization: OAuthAuthorization,
    scopes: list[str],
    *,
    issuer: str,
    secret: str,
    lifetime: timedelta,
    now: datetime,
) -> str:
    """A signed access token for ``scopes`` of the consent ``authorization``."""
    return jwt.encode(
        {
            "iss": issuer,
            "aud": authorization.resource,
            "sub": str(authorization.user_id),
            "org": str(authorization.organization_id),
            "client_id": authorization.client_id,
            "scope": " ".join(scopes),
            "sid": authorization.id,
            "iat": now,
            "exp": now + lifetime,
            "jti": uuid.uuid4().hex,
        },
        _key(secret),
        algorithm=ALGORITHM,
        headers={"typ": TOKEN_TYPE},
    )


def decode_access_token(token: str, *, issuer: str, audience: str, secret: str) -> AccessClaims:
    """The claims of an access token this server issued for ``audience``;
    :class:`InvalidTokenError` for anything else."""
    if jwt.get_unverified_header(token).get("typ") != TOKEN_TYPE:
        raise InvalidTokenError("not an access token")
    claims = jwt.decode(
        token,
        _key(secret),
        algorithms=[ALGORITHM],
        audience=audience,
        issuer=issuer,
        options={"require": list(_REQUIRED)},
    )
    try:
        return AccessClaims(
            user_id=uuid.UUID(claims["sub"]),
            organization_id=uuid.UUID(claims["org"]),
            client_id=str(claims["client_id"]),
            scopes=tuple(str(claims["scope"]).split()),
            authorization_id=str(claims["sid"]),
            expires_at=datetime.fromtimestamp(claims["exp"], UTC),
        )
    except (TypeError, ValueError) as error:
        raise InvalidTokenError("malformed claims") from error


def form_of(body: bytes, content_type: str | None) -> dict[str, str]:
    """The parameters of a token request, which is a form (RFC 6749 §3.2), each named once."""
    if (content_type or "").partition(";")[0].strip().lower() != (
        "application/x-www-form-urlencoded"
    ):
        raise TokenError("invalid_request", "the body is no application/x-www-form-urlencoded")
    try:
        pairs = parse_qsl(
            body.decode(),
            keep_blank_values=True,
            strict_parsing=bool(body),
            errors="strict",
            max_num_fields=_MOST_PARAMETERS,
        )
    except (UnicodeDecodeError, ValueError):
        raise TokenError("invalid_request", "the body is no form") from None
    names = [name for name, _ in pairs]
    if len(set(names)) != len(names):
        raise TokenError("invalid_request", "a parameter is given more than once")
    # A parameter given empty is a parameter not given (RFC 6749 §3.1).
    return {name: value for name, value in pairs if value}


def _required(form: Mapping[str, str], name: str) -> str:
    value = form.get(name)
    if value is None:
        raise TokenError("invalid_request", f"the parameter {name} is required")
    return value


def _challenge_of(verifier: str) -> str:
    """The S256 challenge of a PKCE verifier: the base64url of its SHA-256, without padding."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


async def exchange_code(
    session: AsyncSession,
    settings: Settings,
    tokens: TokenSettings,
    form: Mapping[str, str],
    *,
    now: datetime | None = None,
) -> Issued:
    """The tokens for a code a consent issued (``grant_type=authorization_code``), and commit;
    :class:`TokenError` when the request will not do."""
    moment = now if now is not None else datetime.now(UTC)
    code = _required(form, "code")
    client_id = _required(form, "client_id")
    verifier = _required(form, "code_verifier")
    if not _VERIFIER.fullmatch(verifier):
        raise TokenError(
            "invalid_request", "the code_verifier is no PKCE verifier: 43 to 128 characters"
        )
    consent = await session.scalar(
        select(OAuthAuthorization)
        .where(OAuthAuthorization.code_sha256 == hashlib.sha256(code.encode()).hexdigest())
        .with_for_update()
    )
    try:
        if consent is None:
            raise TokenError("invalid_grant", "the code is not one this server issued")
        if consent.exchanged_at is not None or consent.revoked_at is not None:
            # Presented again: someone else may hold it, so no token of it holds any longer.
            consent.revoked_at = consent.revoked_at or moment
            await session.commit()
            security_event(
                "oauth.code-reused",
                client=consent.client_id,
                consent=consent.id,
                user=None if consent.user_id is None else str(consent.user_id),
            )
            raise TokenError(
                "invalid_grant", "the code was used already: every token it led to is revoked"
            )
        if consent.code_expires_at is None or consent.code_expires_at <= moment:
            raise TokenError("invalid_grant", "the code has expired")
        client = await session.get(OAuthClient, consent.client_id)
        if client is None or client_id != client.id:
            raise TokenError("invalid_grant", "the code was issued to another client")
        # OAuth 2.1 §4.1.3: the redirect URI may be left out, PKCE binding the code; if given,
        # it is the one the code was sent to.
        redirect_uri = form.get("redirect_uri")
        if redirect_uri is not None and redirect_uri != consent.redirect_uri:
            raise TokenError("invalid_grant", "the code was sent to another redirect_uri")
        if not hmac.compare_digest(_challenge_of(verifier), consent.code_challenge):
            raise TokenError("invalid_grant", "the code_verifier is not the code_challenge's")
        _check_resource(settings, consent, form.get("resource"))
        scopes = _allowed(consent.scopes, await _role_of(session, consent))
        consent.exchanged_at = moment
        issued = await _issue(
            session,
            settings,
            tokens,
            consent,
            scopes=scopes,
            moment=moment,
            renewable=REFRESH_GRANT in client.grant_types,
        )
    except TokenError:
        await session.rollback()
        raise
    await session.commit()
    return issued


async def refresh(
    session: AsyncSession,
    settings: Settings,
    tokens: TokenSettings,
    form: Mapping[str, str],
    *,
    now: datetime | None = None,
) -> Issued:
    """New tokens for a refresh token, which is spent (``grant_type=refresh_token``), and commit;
    :class:`TokenError` when the request will not do. The consent's row is locked first, so
    that its refreshes and replays take turns, and each sees what the one before wrote."""
    moment = now if now is not None else datetime.now(UTC)
    digest = opaque_token_digest(_required(form, "refresh_token"))
    client_id = _required(form, "client_id")
    consent_id = await session.scalar(
        select(OAuthRefreshToken.authorization_id).where(OAuthRefreshToken.digest == digest)
    )
    if consent_id is None:
        raise TokenError("invalid_grant", "the refresh token is not one this server issued")
    consent = await session.scalar(
        select(OAuthAuthorization).where(OAuthAuthorization.id == consent_id).with_for_update()
    )
    stored = await session.scalar(
        select(OAuthRefreshToken).where(OAuthRefreshToken.digest == digest)
    )
    try:
        if consent is None or stored is None:  # gone with its membership a moment ago
            raise TokenError("invalid_grant", "the refresh token is not one this server issued")
        if consent.revoked_at is not None:
            raise TokenError("invalid_grant", "the consent was revoked")
        if stored.used_at is not None:
            consent.revoked_at = moment
            await session.commit()
            security_event(
                "oauth.refresh-reused",
                client=consent.client_id,
                consent=consent.id,
                user=None if consent.user_id is None else str(consent.user_id),
            )
            raise TokenError(
                "invalid_grant",
                "the refresh token was used already: every token of the consent is revoked",
            )
        if stored.expires_at <= moment:
            raise TokenError("invalid_grant", "the refresh token has expired")
        if client_id != consent.client_id:
            raise TokenError("invalid_grant", "the refresh token was issued to another client")
        client = await session.get(OAuthClient, consent.client_id)
        if client is None or REFRESH_GRANT not in client.grant_types:
            raise TokenError(
                "unauthorized_client", "the client did not register the refresh_token grant"
            )
        _check_resource(settings, consent, form.get("resource"))
        asked = _scopes_asked(form, consent)
        scopes = _allowed(
            [scope for scope in consent.scopes if scope in asked], await _role_of(session, consent)
        )
        stored.used_at = moment
        # Spent before the next one is kept: a consent has one unspent refresh token at most.
        await session.flush()
        issued = await _issue(
            session, settings, tokens, consent, scopes=scopes, moment=moment, renewable=True
        )
    except TokenError:
        await session.rollback()
        raise
    await session.commit()
    return issued


def _scopes_asked(form: Mapping[str, str], consent: OAuthAuthorization) -> list[str]:
    """The scopes a refresh asks for: those it names, all of them granted by the consent, or
    the consent's when it names none (RFC 6749 §6)."""
    if "scope" not in form:
        return list(consent.scopes)
    asked = form["scope"].split(" ")
    # What the consent granted is all well formed; anything else, an empty name or one of other
    # characters, is refused with it, and not repeated back (RFC 6749 §5.2).
    if not set(asked) <= set(consent.scopes):
        raise TokenError("invalid_scope", "the consent does not grant every scope asked for")
    return asked


def _check_resource(settings: Settings, consent: OAuthAuthorization, resource: str | None) -> None:
    """The resource, if the request names one, must be the one the person consented to (RFC
    8707), compared as resources are."""
    try:
        named = None if resource is None else canonical(resource)
    except ValueError:  # no URI at all
        named = ""
    if named is not None and named != consent.resource:
        raise TokenError("invalid_target", "the resource is not the one the person consented to")
    if consent.resource != resource_of(settings):
        # Issued by a server at another address, which this one no longer is.
        raise TokenError("invalid_grant", "the consent was given to another server")


async def _role_of(session: AsyncSession, consent: OAuthAuthorization) -> Role | None:
    """The role of the member who consented, as it is now; None once they are no longer active."""
    return await session.scalar(
        select(Membership.role)
        .join(User, User.id == Membership.user_id)
        .where(
            Membership.organization_id == consent.organization_id,
            Membership.user_id == consent.user_id,
            User.is_active.is_(True),
        )
    )


def _allowed(scopes: list[str], role: Role | None) -> list[str]:
    """Of ``scopes``, those ``role`` allows; a :class:`TokenError` when it allows none."""
    known = authorizations.SCOPES
    allowed = [
        scope
        for scope in scopes
        if role is not None and scope in known and known[scope] in ROLE_PERMISSIONS[role]
    ]
    if not allowed:
        # Whether the member left, was deactivated or lost the permission is not the client's
        # to know.
        raise TokenError("invalid_grant", "the consent no longer grants any scope")
    return allowed


async def _issue(
    session: AsyncSession,
    settings: Settings,
    tokens: TokenSettings,
    consent: OAuthAuthorization,
    *,
    scopes: list[str],
    moment: datetime,
    renewable: bool,
) -> Issued:
    """A new access token of the consent, and when it is ``renewable`` a refresh token, added to
    the session, kept as its digest."""
    access_token = issue_access_token(
        consent,
        scopes,
        issuer=issuer_of(settings),
        secret=tokens.secret,
        lifetime=tokens.access_lifetime,
        now=moment,
    )
    refresh_token = new_opaque_token() if renewable else None
    if refresh_token is not None:
        session.add(
            OAuthRefreshToken(
                authorization_id=consent.id,
                digest=opaque_token_digest(refresh_token),
                expires_at=moment + tokens.refresh_lifetime,
            )
        )
        await session.flush()
    return Issued(
        access_token=access_token,
        expires_in=int(tokens.access_lifetime.total_seconds()),
        refresh_token=refresh_token,
        scopes=scopes,
    )
