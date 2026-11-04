"""Issuing API keys, and finding the member a key acts for.

A key is ``sefk_`` and 43 characters of base64url, 256 random bits. The prefix tells a key from
an access token in the same ``Authorization: Bearer`` header, and lets a secret scanner
recognize a key that leaked. The database keeps the key's SHA-256 digest, never the key, as it
does for refresh tokens: a digest of so much randomness needs no salt or slow hash.

A key holds some of the permissions keys may hold (:data:`KEY_PERMISSIONS`), each one the
member's role granted when it was issued. What it allows is decided on every request with the
role the member holds then, so a demoted member's keys lose what the new role does not grant.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.auth.permissions import ROLE_PERMISSIONS, Permission
from sef_api.auth.tokens import new_opaque_token, opaque_token_digest
from sef_api.locks import lock_api_keys
from sef_api.models import ApiKey, Membership, Role

__all__ = [
    "MAX_KEYS_PER_MEMBER",
    "PREFIX",
    "SHOWN",
    "Grant",
    "Holder",
    "Issued",
    "NotGrantedError",
    "TooManyKeysError",
    "authenticate",
    "is_api_key",
    "issue",
    "still_works",
    "working_keys",
]

#: How every key begins.
PREFIX: Final = "sefk_"
#: How many characters of a key are kept in clear, by which people tell keys apart: the
#: prefix and seven more, 42 of the key's 256 random bits.
SHOWN: Final = 12
#: The most keys a member may have in an organization that are neither revoked nor expired.
MAX_KEYS_PER_MEMBER: Final = 20


class NotGrantedError(Exception):
    """The member's role does not grant a permission the key was to hold."""

    def __init__(self, permission: Permission) -> None:
        super().__init__(permission)
        self.permission = permission


class TooManyKeysError(Exception):
    """The member has as many keys as they may."""


@dataclass(frozen=True)
class Grant:
    """The API key a caller came with: which key it is, and what it allows."""

    key_id: uuid.UUID
    permissions: frozenset[Permission]


@dataclass(frozen=True)
class Holder:
    """The member a key acts for, the role they hold now, and the key."""

    user_id: uuid.UUID
    organization_id: uuid.UUID
    role: Role
    grant: Grant


@dataclass(frozen=True)
class Issued:
    """A new key's row, and the key itself, which is shown this once."""

    key: ApiKey
    secret: str


def is_api_key(credential: str) -> bool:
    """Whether ``credential`` is meant as an API key rather than an access token."""
    return credential.startswith(PREFIX)


def _live(moment: datetime) -> tuple[ColumnElement[bool], ...]:
    """The conditions of a key that works at ``moment``: neither revoked nor expired."""
    return (
        ApiKey.revoked_at.is_(None),
        or_(ApiKey.expires_at.is_(None), ApiKey.expires_at > moment),
    )


async def working_keys(
    session: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID, moment: datetime
) -> int:
    """How many of the member's keys in the organization work at ``moment``."""
    counted = await session.scalar(
        select(func.count())
        .select_from(ApiKey)
        .where(ApiKey.organization_id == organization_id, ApiKey.user_id == user_id)
        .where(*_live(moment))
    )
    return counted or 0


async def issue(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    role: Role,
    name: str,
    permissions: Iterable[Permission],
    expires_at: datetime | None = None,
    now: datetime | None = None,
) -> Issued:
    """Issue a key with which a machine client acts for the member with ``permissions``, and
    commit.

    ``permissions`` are among :data:`KEY_PERMISSIONS`; the request admits no other, and the
    table refuses them. Raises :class:`NotGrantedError` for one that ``role``, the member's
    role now, does not grant, and :class:`TooManyKeysError` when the member already has
    :data:`MAX_KEYS_PER_MEMBER` keys that work.
    """
    held = sorted(set(permissions))
    for permission in held:
        if permission not in ROLE_PERMISSIONS[role]:
            raise NotGrantedError(permission)
    moment = now or datetime.now(UTC)
    # Counting the member's keys and issuing one more take turns with other issuing.
    await lock_api_keys(session, organization_id)
    if await working_keys(session, organization_id, user_id, moment) >= MAX_KEYS_PER_MEMBER:
        raise TooManyKeysError
    secret = PREFIX + new_opaque_token()
    key = ApiKey(
        organization_id=organization_id,
        user_id=user_id,
        name=name,
        prefix=secret[:SHOWN],
        digest=opaque_token_digest(secret),
        permissions=[permission.value for permission in held],
        expires_at=expires_at,
    )
    session.add(key)
    await session.commit()
    return Issued(key, secret)


async def authenticate(
    session: AsyncSession, secret: str, *, now: datetime | None = None
) -> Holder | None:
    """The member the key ``secret`` acts for and what it allows; None for a key that does not
    exist, is revoked or has expired.

    Whether the member's account is still active is the caller's to check, as it is for an
    access token; a key without a membership does not exist.
    """
    row = (
        await session.execute(
            select(
                ApiKey.id,
                ApiKey.user_id,
                ApiKey.organization_id,
                Membership.role,
                ApiKey.permissions,
            )
            .join(
                Membership,
                (Membership.organization_id == ApiKey.organization_id)
                & (Membership.user_id == ApiKey.user_id),
            )
            .where(ApiKey.digest == opaque_token_digest(secret))
            .where(*_live(now or datetime.now(UTC)))
        )
    ).one_or_none()
    if row is None:
        return None
    key_id, user_id, organization_id, role, permissions = row
    grant = Grant(key_id, frozenset(map(Permission, permissions)))
    return Holder(user_id, organization_id, role, grant)


async def still_works(
    session: AsyncSession, key_id: uuid.UUID, *, now: datetime | None = None
) -> bool:
    """Whether the key with ``key_id`` is still neither revoked nor expired: for a request whose
    work outlasts the moment its key was checked."""
    found = await session.scalar(
        select(ApiKey.id).where(ApiKey.id == key_id).where(*_live(now or datetime.now(UTC)))
    )
    return found is not None
