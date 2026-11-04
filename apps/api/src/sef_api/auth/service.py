"""Sign-up, sign-in, token refresh and sign-out, on the database.

Each function receives the request's session and commits its own unit of work. Failures are
exceptions that the routes turn into responses; none of them says which half of a credential
was wrong.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.auth.passwords import hash_password, needs_rehash, verify_password
from sef_api.auth.tokens import issue_access_token, new_opaque_token, opaque_token_digest
from sef_api.locks import lock_organization
from sef_api.models import Membership, Organization, RefreshToken, Role, User
from sef_api.settings import Settings

__all__ = [
    "AuthenticationError",
    "EmailTakenError",
    "InvalidRefreshTokenError",
    "NotAMemberError",
    "OrganizationRequiredError",
    "SignedIn",
    "TokenSettings",
    "login",
    "logout",
    "normalize_email",
    "refresh",
    "register",
]


@dataclass(frozen=True)
class TokenSettings:
    """How tokens are signed and how long they live."""

    secret: str
    access_lifetime: timedelta
    refresh_lifetime: timedelta

    @classmethod
    def from_settings(cls, settings: Settings) -> TokenSettings:
        return cls(
            secret=settings.jwt_secret.get_secret_value(),
            access_lifetime=settings.access_token_lifetime,
            refresh_lifetime=settings.refresh_token_lifetime,
        )


@dataclass(frozen=True)
class SignedIn:
    """A new pair of tokens for a person's session in one organization."""

    user: User
    organization: Organization
    role: Role
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime


class AuthenticationError(Exception):
    """Wrong e-mail address or password, or an account that may not sign in."""


class EmailTakenError(Exception):
    """An account with this e-mail address exists already."""


class NotAMemberError(Exception):
    """The person is not a member of the organization asked for (or of any organization)."""


class OrganizationRequiredError(Exception):
    """The person belongs to several organizations and must say which one."""

    def __init__(self, memberships: list[tuple[Organization, Role]]) -> None:
        super().__init__("organization_id is required")
        self.memberships = memberships


class InvalidRefreshTokenError(Exception):
    """Unknown, expired, spent or revoked refresh token, or a session that has ended."""


def normalize_email(email: str) -> str:
    """E-mail addresses are compared and stored in lower case, without surrounding spaces."""
    return email.strip().lower()


async def register(
    session: AsyncSession,
    tokens: TokenSettings,
    *,
    email: str,
    password: str,
    organization_name: str,
) -> SignedIn:
    """Create an account and its organization, make the person its owner, and sign them in.

    The unique e-mail address is the database's to enforce: checking first and inserting after
    would leave a gap for two registrations at once.
    """
    user = User(email=normalize_email(email), password_hash=await hash_password(password))
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as error:  # uq_users_email
        await session.rollback()
        raise EmailTakenError from error
    organization = Organization(name=organization_name.strip())
    session.add(organization)
    await session.flush()
    session.add(Membership(organization_id=organization.id, user_id=user.id, role=Role.OWNER))
    signed_in = await _sign_in(
        session, tokens, user, organization, Role.OWNER, family_id=uuid.uuid4()
    )
    await session.commit()
    return signed_in


async def login(
    session: AsyncSession,
    tokens: TokenSettings,
    *,
    email: str,
    password: str,
    organization_id: uuid.UUID | None = None,
) -> SignedIn:
    """Check the password and sign the person in to one of their organizations.

    The membership is read once more under the organization's lock (share mode): a removal at
    the same moment either comes first and is seen, or waits and then revokes this session.
    """
    user = await session.scalar(select(User).where(User.email == normalize_email(email)))
    if not await verify_password(user.password_hash if user else None, password):
        raise AuthenticationError
    assert user is not None  # a password only verifies against a real account's hash
    if not user.is_active:
        raise AuthenticationError
    renewed_hash = await hash_password(password) if needs_rehash(user.password_hash) else None
    rows = await session.execute(
        select(Organization, Membership.role)
        .join(Membership, Membership.organization_id == Organization.id)
        .where(Membership.user_id == user.id)
        .order_by(Organization.name, Organization.id)
    )
    memberships = [(organization, role) for organization, role in rows]
    if not memberships:
        raise NotAMemberError
    if organization_id is None:
        if len(memberships) > 1:
            raise OrganizationRequiredError(memberships)
        organization = memberships[0][0]
    else:
        chosen = [o for o, _ in memberships if o.id == organization_id]
        if not chosen:
            raise NotAMemberError
        organization = chosen[0]
    await lock_organization(session, organization.id, shared=True)
    role = await session.scalar(
        select(Membership.role).where(
            Membership.organization_id == organization.id, Membership.user_id == user.id
        )
    )
    if role is None:
        raise NotAMemberError
    if renewed_hash is not None:  # changed only now, after the lock, like every other row
        user.password_hash = renewed_hash
    signed_in = await _sign_in(session, tokens, user, organization, role, family_id=uuid.uuid4())
    await session.commit()
    return signed_in


async def refresh(
    session: AsyncSession,
    tokens: TokenSettings,
    *,
    refresh_token: str,
    now: datetime | None = None,
) -> SignedIn:
    """Spend a refresh token for a new pair, in the same session.

    A token is good once. Presenting a spent one again means that someone else has a copy, and
    the whole session (the token's family) is revoked. The role is read again, so a change of
    role takes effect at the next refresh at the latest.

    A token that can do nothing (unknown, revoked, or expired before it was spent) is refused
    without taking any lock. Otherwise the organization is locked shared and the session's
    tokens exclusively, both in a fixed order, before anything is decided. So a refresh and a
    removal of the same person take turns, and so do the refreshes, replays and sign-outs of
    one session: whichever comes second sees what the first one wrote.
    """
    moment = now if now is not None else datetime.now(UTC)
    digest = opaque_token_digest(refresh_token)
    found = await _find_live(session, digest, moment)
    if found is None:
        raise InvalidRefreshTokenError
    await lock_organization(session, found.organization_id, shared=True)
    await _lock_family(session, found.family_id)
    stored = await session.scalar(select(RefreshToken).where(RefreshToken.digest == digest))
    if stored is None:  # removed with its organization or account a moment ago
        raise InvalidRefreshTokenError
    if stored.used_at is not None or stored.revoked_at is not None:
        await _revoke_family(session, stored.family_id, moment)
        await session.commit()
        raise InvalidRefreshTokenError
    # Not expired: _find_live refused an unspent token past its expiry, which does not move.
    row = (
        await session.execute(
            select(User, Organization, Membership.role)
            .join(Membership, Membership.user_id == User.id)
            .join(Organization, Organization.id == Membership.organization_id)
            .where(User.id == stored.user_id, Organization.id == stored.organization_id)
        )
    ).one_or_none()
    if row is None or not row[0].is_active:
        await _revoke_family(session, stored.family_id, moment)
        await session.commit()
        raise InvalidRefreshTokenError
    user, organization, role = row
    stored.used_at = moment
    signed_in = await _sign_in(
        session, tokens, user, organization, role, family_id=stored.family_id, now=moment
    )
    await session.commit()
    return signed_in


async def logout(session: AsyncSession, *, refresh_token: str, now: datetime | None = None) -> None:
    """End the session the refresh token belongs to. A token that can do nothing (unknown,
    revoked, or expired before it was spent) changes nothing and takes no lock. The locks are
    those of :func:`refresh`, so a sign-out also revokes a token that a refresh issued while it
    waited."""
    moment = now if now is not None else datetime.now(UTC)
    found = await _find_live(session, opaque_token_digest(refresh_token), moment)
    if found is None:
        return
    await lock_organization(session, found.organization_id, shared=True)
    await _lock_family(session, found.family_id)
    await _revoke_family(session, found.family_id, moment)
    await session.commit()


async def _sign_in(
    session: AsyncSession,
    tokens: TokenSettings,
    user: User,
    organization: Organization,
    role: Role,
    *,
    family_id: uuid.UUID,
    now: datetime | None = None,
) -> SignedIn:
    moment = now if now is not None else datetime.now(UTC)
    access_token, access_expires_at = issue_access_token(
        user.id,
        organization.id,
        role,
        secret=tokens.secret,
        lifetime=tokens.access_lifetime,
        now=moment,
    )
    token = new_opaque_token()
    refresh_expires_at = moment + tokens.refresh_lifetime
    session.add(
        RefreshToken(
            organization_id=organization.id,
            user_id=user.id,
            family_id=family_id,
            digest=opaque_token_digest(token),
            expires_at=refresh_expires_at,
        )
    )
    await session.flush()
    return SignedIn(
        user=user,
        organization=organization,
        role=role,
        access_token=access_token,
        access_expires_at=access_expires_at,
        refresh_token=token,
        refresh_expires_at=refresh_expires_at,
    )


@dataclass(frozen=True)
class _Live:
    organization_id: uuid.UUID
    family_id: uuid.UUID


async def _find_live(session: AsyncSession, digest: str, moment: datetime) -> _Live | None:
    """Where a refresh token belongs, read without a lock; None for a token that can do
    nothing: unknown, revoked (its session was revoked with it), or expired before it was
    spent. A spent token can still end its session, so it counts."""
    row = (
        await session.execute(
            select(
                RefreshToken.organization_id,
                RefreshToken.family_id,
                RefreshToken.used_at,
                RefreshToken.revoked_at,
                RefreshToken.expires_at,
            ).where(RefreshToken.digest == digest)
        )
    ).one_or_none()
    if (
        row is None
        or row.revoked_at is not None
        or (row.used_at is None and row.expires_at <= moment)
    ):
        return None
    return _Live(row.organization_id, row.family_id)


async def _lock_family(session: AsyncSession, family_id: uuid.UUID) -> None:
    """Lock every token of one session, in one order, so that two of its refreshes, replays
    or sign-outs take turns instead of deadlocking. The statements after the lock see what the
    one before wrote, such as a token that a refresh issued while this one waited."""
    await session.execute(
        select(RefreshToken.id)
        .where(RefreshToken.family_id == family_id)
        .order_by(RefreshToken.id)
        .with_for_update()
    )


async def _revoke_family(session: AsyncSession, family_id: uuid.UUID, now: datetime) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
