"""Invitations: a one-time code with which a person joins an organization in a role.

There is no mail service (the free-tier stack has none, and the self-hosted mode makes no
external calls), so the owner who invites receives the code once and passes it on. The table
keeps only the code's SHA-256 digest. An address has at most one open invitation per
organization: inviting it again replaces the open one. The code is redeemed with
``POST /auth/accept-invitation`` (:func:`sef_api.auth.service.accept_invitation`).

Issuing, revoking and accepting invitations change who may join, so like every change to the
members they lock the organization first (:func:`~sef_api.locks.lock_organization`). An
invitation stops working when the owner who issued it may no longer invite: removing or demoting
them withdraws their open invitations (:func:`withdraw_invitations_of`), and accepting checks the
issuer once more.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.auth.service import normalize_email
from sef_api.auth.tokens import new_opaque_token, opaque_token_digest
from sef_api.locks import lock_organization
from sef_api.models import Invitation, Membership, Role, User

__all__ = [
    "INVITATION_LIFETIME",
    "AlreadyAMemberError",
    "InvitationAcceptedError",
    "InvitationNotFoundError",
    "Issued",
    "invite",
    "list_open",
    "revoke",
    "withdraw_invitations_of",
]

INVITATION_LIFETIME: Final = timedelta(days=7)


@dataclass(frozen=True)
class Issued:
    """A new invitation and its code, which exists only in this object and in the response."""

    invitation: Invitation
    code: str


class AlreadyAMemberError(Exception):
    """The address belongs to a member of the organization already."""


class InvitationNotFoundError(Exception):
    """No invitation with this id in the caller's organization."""


class InvitationAcceptedError(Exception):
    """The invitation has been accepted; it can no longer be revoked."""


async def invite(
    session: AsyncSession,
    organization_id: uuid.UUID,
    invited_by: uuid.UUID,
    *,
    email: str,
    role: Role,
    now: datetime | None = None,
) -> Issued:
    """Invite ``email`` to join the organization as ``role``; an open invitation for the same
    address in this organization is revoked."""
    moment = now if now is not None else datetime.now(UTC)
    address = normalize_email(email)
    await lock_organization(session, organization_id)
    member = await session.scalar(
        select(Membership.user_id)
        .join(User, User.id == Membership.user_id)
        .where(Membership.organization_id == organization_id, User.email == address)
    )
    if member is not None:
        raise AlreadyAMemberError
    await session.execute(
        update(Invitation)
        .where(
            Invitation.organization_id == organization_id,
            Invitation.email == address,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
        )
        .values(revoked_at=moment)
    )
    code = new_opaque_token()
    invitation = Invitation(
        organization_id=organization_id,
        email=address,
        role=role,
        digest=opaque_token_digest(code),
        invited_by=invited_by,
        created_at=moment,
        expires_at=moment + INVITATION_LIFETIME,
    )
    session.add(invitation)
    await session.commit()
    return Issued(invitation, code)


async def list_open(
    session: AsyncSession, organization_id: uuid.UUID, *, now: datetime | None = None
) -> list[Invitation]:
    """The organization's invitations that can still be accepted, the newest first."""
    moment = now if now is not None else datetime.now(UTC)
    invitations = await session.scalars(
        select(Invitation)
        .where(
            Invitation.organization_id == organization_id,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
            Invitation.expires_at > moment,
        )
        .order_by(Invitation.created_at.desc(), Invitation.email)
    )
    return list(invitations)


async def revoke(
    session: AsyncSession,
    organization_id: uuid.UUID,
    invitation_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> None:
    """Revoke an invitation so that its code no longer works; revoking twice changes nothing."""
    await lock_organization(session, organization_id)
    invitation = await session.scalar(
        select(Invitation)
        .where(Invitation.id == invitation_id, Invitation.organization_id == organization_id)
        .with_for_update()
    )
    if invitation is None:
        raise InvitationNotFoundError
    if invitation.accepted_at is not None:
        raise InvitationAcceptedError
    if invitation.revoked_at is None:
        invitation.revoked_at = now if now is not None else datetime.now(UTC)
        await session.commit()


async def withdraw_invitations_of(
    session: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID, *, now: datetime
) -> None:
    """Revoke the open invitations that ``user_id`` issued in the organization, because they
    may no longer invite. The caller holds the organization's lock and commits."""
    await session.execute(
        update(Invitation)
        .where(
            Invitation.organization_id == organization_id,
            Invitation.invited_by == user_id,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
