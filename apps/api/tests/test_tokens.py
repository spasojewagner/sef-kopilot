"""Access tokens and refresh tokens: what is signed, what is refused, what is stored."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest

from sef_api.auth.tokens import (
    AUDIENCE,
    ISSUER,
    InvalidTokenError,
    decode_access_token,
    issue_access_token,
    new_refresh_token,
    refresh_token_digest,
)
from sef_api.models import Role

from .conftest import TEST_JWT_SECRET

USER, ORGANIZATION = uuid.uuid4(), uuid.uuid4()


def issue(*, now: datetime | None = None, secret: str = TEST_JWT_SECRET) -> str:
    token, _ = issue_access_token(
        USER, ORGANIZATION, Role.ACCOUNTANT, secret=secret, lifetime=timedelta(minutes=15), now=now
    )
    return token


def forge(claims: dict[str, Any], *, headers: dict[str, Any] | None = None) -> str:
    """A token with the right key and the given claims and header."""
    now = datetime.now(UTC)
    payload = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": str(USER),
        "org": str(ORGANIZATION),
        "role": "accountant",
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "jti": "1",
    } | claims
    return jwt.encode(
        {k: v for k, v in payload.items() if v is not None},
        TEST_JWT_SECRET,
        algorithm="HS256",
        headers={"typ": "at+jwt"} | (headers or {}),
    )


def test_an_access_token_says_who_acts_where_and_in_which_role() -> None:
    claims = decode_access_token(issue(), secret=TEST_JWT_SECRET)

    assert (claims.user_id, claims.organization_id, claims.role) == (
        USER,
        ORGANIZATION,
        Role.ACCOUNTANT,
    )
    assert timedelta(minutes=14) < claims.expires_at - datetime.now(UTC) <= timedelta(minutes=15)


def test_an_access_token_has_the_access_token_type() -> None:
    assert jwt.get_unverified_header(issue()) == {"alg": "HS256", "typ": "at+jwt"}


def test_an_expired_access_token_is_refused() -> None:
    token = issue(now=datetime.now(UTC) - timedelta(minutes=16))

    with pytest.raises(InvalidTokenError, match="expired"):
        decode_access_token(token, secret=TEST_JWT_SECRET)


def test_a_token_signed_with_another_key_is_refused() -> None:
    with pytest.raises(InvalidTokenError):
        decode_access_token(issue(secret="other" * 8), secret=TEST_JWT_SECRET)


@pytest.mark.parametrize(
    "claims",
    [
        {"aud": "another-api"},
        {"iss": "someone-else"},
        {"org": None},
        {"role": None},
        {"jti": None},
        {"sub": "not-a-uuid"},
        {"role": "admin"},
    ],
    ids=["audience", "issuer", "no org", "no role", "no jti", "bad sub", "unknown role"],
)
def test_a_token_with_wrong_or_missing_claims_is_refused(claims: dict[str, Any]) -> None:
    with pytest.raises(InvalidTokenError):
        decode_access_token(forge(claims), secret=TEST_JWT_SECRET)


def test_a_jwt_of_another_type_is_refused() -> None:
    with pytest.raises(InvalidTokenError, match="not an access token"):
        decode_access_token(forge({}, headers={"typ": "JWT"}), secret=TEST_JWT_SECRET)


def test_an_unsigned_token_is_refused() -> None:
    unsigned = jwt.encode({"sub": str(USER)}, key=None, algorithm="none", headers={"typ": "at+jwt"})

    with pytest.raises(InvalidTokenError):
        decode_access_token(unsigned, secret=TEST_JWT_SECRET)


def test_garbage_is_refused() -> None:
    with pytest.raises(InvalidTokenError):
        decode_access_token("not.a.token", secret=TEST_JWT_SECRET)


def test_a_refresh_token_is_random_and_stored_by_its_digest() -> None:
    token = new_refresh_token()

    assert len(token) == 43  # 32 bytes, URL-safe base64 without padding
    assert token != new_refresh_token()
    assert refresh_token_digest(token) == hashlib.sha256(token.encode()).hexdigest()
