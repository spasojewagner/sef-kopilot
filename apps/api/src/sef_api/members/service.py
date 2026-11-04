"""Listing members, changing their roles and removing them, on the database.

An organization always keeps at least one active owner. Changes to the members of one
organization take turns: each takes the organization's lock first
(:func:`~sef_api.locks.lock_organization`), so two owners cannot both step down at the same
moment and leave nobody in charge.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.locks import lock_organization
from sef_api.models import Membership, RefreshToken, Role, User

__all__ = [
    "LastOwnerError",
    "Member",
    "MemberNotFoundError",
    "change_role",
    "list_members",
    "remove",
]


@dataclass(frozen=True)
class Member:
    """A person and the role they hold in the organization."""

    user: User
    role: Role
    joined_at: datetime


class MemberNotFoundError(Exception):
    """No member with this id in the caller's organization."""


class LastOwnerError(Exception):
    """The change would leave the organization without an active owner."""


async def list_members(session: AsyncSession, organization_id: uuid.UUID) -> list[Member]:
    """The organization's members, by e-mail address."""
    rows = await session.execute(
        select(User, Membership.role, Membership.created_at)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.organization_id == organization_id)
        .order_by(User.email)
    )
    return [Member(user, role, joined_at) for user, role, joined_at in rows]


async def change_role(
    session: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID, role: Role
) -> Member:
    """Give a member another role; the last active owner cannot be given another one."""
    await lock_organization(session, organization_id)
    membership, user = await _find(session, organization_id, user_id)
    if membership.role is Role.OWNER and role is not Role.OWNER:
        await _keep_an_owner(session, organization_id, leaving=user_id)
    membership.role = role
    await session.commit()
    return Member(user, role, membership.created_at)


async def remove(
    session: AsyncSession,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> None:
    """Remove a member and end their sessions in the organization; not the last active owner."""
    await lock_organization(session, organization_id)
    membership, _ = await _find(session, organization_id, user_id)
    if membership.role is Role.OWNER:
        await _keep_an_owner(session, organization_id, leaving=user_id)
    await session.delete(membership)
    await session.execute(
        update(RefreshToken)
        .where(
            RefreshToken.organization_id == organization_id,
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=now or datetime.now(UTC))
    )
    await session.commit()


async def _find(
    session: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID
) -> tuple[Membership, User]:
    row = (
        await session.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.organization_id == organization_id, Membership.user_id == user_id)
        )
    ).one_or_none()
    if row is None:
        raise MemberNotFoundError
    membership, user = row
    return membership, user


async def _keep_an_owner(
    session: AsyncSession, organization_id: uuid.UUID, *, leaving: uuid.UUID
) -> None:
    """Refuse the change unless an active owner other than ``leaving`` remains; a deactivated
    owner cannot act, so it does not count."""
    others = await session.scalar(
        select(func.count())
        .select_from(Membership)
        .join(User, User.id == Membership.user_id)
        .where(
            Membership.organization_id == organization_id,
            Membership.role == Role.OWNER,
            Membership.user_id != leaving,
            User.is_active.is_(True),
        )
    )
    if not others:
        raise LastOwnerError
