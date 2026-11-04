"""Access tokens (JWT, HS256) and refresh tokens (random, stored only as a SHA-256 digest).

An access token says who calls, for which organization and in which role, and expires after
minutes; it is checked without the database. Its header type is ``at+jwt`` (RFC 9068), and the
algorithm, issuer, audience and expiry are all required and verified, so a token minted for
another purpose or with another algorithm (``none`` included) is refused.

A refresh token is 256 random bits. The database keeps its SHA-256 digest, never the token: a
leaked table holds nothing that signs anyone in, and a digest of so much randomness needs no
salt or slow hash.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

import jwt

from sef_api.models import Role

__all__ = [
    "AccessClaims",
    "InvalidTokenError",
    "decode_access_token",
    "issue_access_token",
    "new_refresh_token",
    "refresh_token_digest",
]

ALGORITHM: Final = "HS256"
ISSUER: Final = "sef-kopilot"
AUDIENCE: Final = "sef-kopilot-api"
TOKEN_TYPE: Final = "at+jwt"
_REQUIRED: Final = ("exp", "iat", "iss", "aud", "sub", "org", "role", "jti")

InvalidTokenError = jwt.InvalidTokenError


@dataclass(frozen=True)
class AccessClaims:
    """What an access token asserts."""

    user_id: uuid.UUID
    organization_id: uuid.UUID
    role: Role
    expires_at: datetime


def issue_access_token(
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    role: Role,
    *,
    secret: str,
    lifetime: timedelta,
    now: datetime | None = None,
) -> tuple[str, datetime]:
    """A signed access token and the moment it expires."""
    issued_at = now if now is not None else datetime.now(UTC)
    expires_at = issued_at + lifetime
    token = jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": str(user_id),
            "org": str(organization_id),
            "role": role.value,
            "iat": issued_at,
            "exp": expires_at,
            "jti": uuid.uuid4().hex,
        },
        secret,
        algorithm=ALGORITHM,
        headers={"typ": TOKEN_TYPE},
    )
    return token, expires_at


def decode_access_token(token: str, *, secret: str) -> AccessClaims:
    """The claims of a valid access token; :class:`InvalidTokenError` for anything else."""
    if jwt.get_unverified_header(token).get("typ") != TOKEN_TYPE:
        raise InvalidTokenError("not an access token")
    claims = jwt.decode(
        token,
        secret,
        algorithms=[ALGORITHM],
        audience=AUDIENCE,
        issuer=ISSUER,
        options={"require": list(_REQUIRED)},
    )
    try:
        return AccessClaims(
            user_id=uuid.UUID(claims["sub"]),
            organization_id=uuid.UUID(claims["org"]),
            role=Role(claims["role"]),
            expires_at=datetime.fromtimestamp(claims["exp"], UTC),
        )
    except (TypeError, ValueError) as error:
        raise InvalidTokenError("malformed claims") from error


def new_refresh_token() -> str:
    """A new refresh token: 256 random bits, URL-safe."""
    return secrets.token_urlsafe(32)


def refresh_token_digest(token: str) -> str:
    """The SHA-256 digest by which a refresh token is stored and looked up."""
    return hashlib.sha256(token.encode()).hexdigest()
