"""Sign-up, sign-in, accepting an invitation, token refresh and sign-out, on the database.

Each function receives the request's session and commits its own unit of work. Failures are
exceptions that the routes turn into responses; none of them says which half of a credential
was wrong. A password is checked only while its e-mail address may be tried again, and each
wrong one is counted (:class:`PasswordGuard`, ADR-0018).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import ColumnElement, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.auth.passwords import MINIMUM_LENGTH, hash_password, needs_rehash, verify_password
from sef_api.auth.permissions import ROLE_PERMISSIONS, Permission
from sef_api.auth.tokens import issue_access_token, new_opaque_token, opaque_token_digest
from sef_api.locks import lock_organization
from sef_api.logs import security_event
from sef_api.models import Invitation, Membership, Organization, RefreshToken, Role, User
from sef_api.settings import Settings

__all__ = [
    "AuthenticationError",
    "EmailTakenError",
    "InvalidInvitationError",
    "InvalidRefreshTokenError",
    "NewPasswordTooShortError",
    "NotAMemberError",
    "OrganizationRequiredError",
    "PasswordGuard",
    "SignedIn",
    "TokenSettings",
    "TooManyAttemptsError",
    "accept_invitation",
    "login",
    "logout",
    "normalize_email",
    "refresh",
    "register",
]


class PasswordGuard(Protocol):
    """Counts the failed password checks of each e-mail address against a limit."""

    def wait(self, email: str) -> float:
        """Seconds until a password for ``email`` may be checked again; 0 when it may now."""

    def failed(self, email: str) -> None:
        """A password for ``email`` was wrong."""

    def passed(self, email: str) -> None:
        """A password for ``email`` was right."""


class TooManyAttemptsError(Exception):
    """Too many wrong passwords for the e-mail address; no password is checked until ``wait``
    seconds have passed."""

    def __init__(self, wait: float) -> None:
        super().__init__(wait)
        self.wait = wait


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


class InvalidInvitationError(Exception):
    """Unknown, expired, revoked or already accepted invitation code."""


class NewPasswordTooShortError(Exception):
    """The password for a new account is shorter than the minimum."""


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
    guard: PasswordGuard,
    organization_id: uuid.UUID | None = None,
) -> SignedIn:
    """Check the password and sign the person in to one of their organizations.

    Raises :class:`TooManyAttemptsError`, before any password is checked, while ``guard``
    holds the address back. The membership is read once more under the organization's lock
    (share mode): a removal at the same moment either comes first and is seen, or waits and
    then revokes this session.
    """
    address = normalize_email(email)
    user = await session.scalar(select(User).where(User.email == address))
    if not await _verify(guard, address, user.password_hash if user else None, password):
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


async def accept_invitation(
    session: AsyncSession,
    tokens: TokenSettings,
    *,
    code: str,
    password: str,
    guard: PasswordGuard,
    now: datetime | None = None,
) -> SignedIn:
    """Join the organization of an invitation and sign in to it.

    Without an account for the invited address, one is created with ``password``; with one,
    ``password`` must be its password, so that a code alone never gives access to an account.
    That password is checked and counted as at sign-in, by ``guard``. A code is good once, and
    only while the owner who issued it may still invite. A person who is a member already
    keeps the role they have.

    The password is checked, or the new one hashed, before the organization is locked, so that
    a wrong password holds nothing up; under the lock the invitation is checked again.
    """
    moment = now if now is not None else datetime.now(UTC)
    digest = opaque_token_digest(code)
    found = (
        await session.execute(
            select(Invitation.organization_id, Invitation.email).where(
                Invitation.digest == digest, *_open(moment)
            )
        )
    ).one_or_none()
    if found is None:
        raise InvalidInvitationError
    organization_id, email = found
    user = await session.scalar(select(User).where(User.email == email))
    password_hash: str | None = None
    if user is None:
        if len(password) < MINIMUM_LENGTH:
            raise NewPasswordTooShortError
        password_hash = await hash_password(password)
    elif not await _verify(guard, email, user.password_hash, password) or not user.is_active:
        raise AuthenticationError
    elif needs_rehash(user.password_hash):
        password_hash = await hash_password(password)
    # The organization first, as every change to its members does, then the invitation.
    await lock_organization(session, organization_id)
    invitation = await session.scalar(
        select(Invitation).where(Invitation.digest == digest, *_open(moment)).with_for_update()
    )
    if invitation is None or not await _issuer_may_invite(session, invitation):
        raise InvalidInvitationError
    if user is None:
        assert password_hash is not None
        user = User(email=email, password_hash=password_hash)
        session.add(user)
        try:
            await session.flush()
        except IntegrityError as error:  # the address registered a moment ago
            await session.rollback()
            raise EmailTakenError from error
    else:
        if not await session.scalar(select(User.is_active).where(User.id == user.id)):
            raise AuthenticationError  # deactivated or deleted while the password was checked
        if password_hash is not None:
            user.password_hash = password_hash
    membership = await session.scalar(
        select(Membership).where(
            Membership.organization_id == invitation.organization_id,
            Membership.user_id == user.id,
        )
    )
    if membership is None:
        membership = Membership(
            organization_id=invitation.organization_id, user_id=user.id, role=invitation.role
        )
        session.add(membership)
    invitation.accepted_at = moment
    organization = await session.get_one(Organization, invitation.organization_id)
    signed_in = await _sign_in(
        session, tokens, user, organization, membership.role, family_id=uuid.uuid4(), now=moment
    )
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
        # Someone else may hold it: every session of the family ends.
        security_event(
            "session.refresh-reused",
            user=str(stored.user_id),
            organization=str(stored.organization_id),
            family=str(stored.family_id),
        )
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


async def _verify(
    guard: PasswordGuard, email: str, password_hash: str | None, password: str
) -> bool:
    """Whether ``password`` is the one of ``password_hash``, None for an address without an
    account. It is checked only while ``guard`` lets ``email`` try again, and a wrong one is
    counted; raises :class:`TooManyAttemptsError` otherwise."""
    if (waiting := guard.wait(email)) > 0:
        raise TooManyAttemptsError(waiting)
    if not await verify_password(password_hash, password):
        guard.failed(email)
        return False
    guard.passed(email)
    return True


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


def _open(moment: datetime) -> tuple[ColumnElement[bool], ...]:
    """The conditions of an invitation that can still be accepted at ``moment``."""
    return (
        Invitation.accepted_at.is_(None),
        Invitation.revoked_at.is_(None),
        Invitation.expires_at > moment,
    )


async def _issuer_may_invite(session: AsyncSession, invitation: Invitation) -> bool:
    """Whether the member who issued the invitation may still invite. An invitation stops
    working once its issuer is removed, demoted, deactivated or deleted (ADR-0013)."""
    if invitation.invited_by is None:
        return False
    role = await session.scalar(
        select(Membership.role)
        .join(User, User.id == Membership.user_id)
        .where(
            Membership.organization_id == invitation.organization_id,
            Membership.user_id == invitation.invited_by,
            User.is_active.is_(True),
        )
    )
    return role is not None and Permission.MEMBERS_MANAGE in ROLE_PERMISSIONS[role]


async def _revoke_family(session: AsyncSession, family_id: uuid.UUID, now: datetime) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
