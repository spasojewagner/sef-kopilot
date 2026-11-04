"""``/members`` and ``/invitations``: the members of the caller's organization, their roles,
and the invitations to join it."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.auth.dependencies import Principal, require
from sef_api.auth.permissions import Permission
from sef_api.auth.routes import NO_STORE, Problem, UserOut
from sef_api.db import get_session
from sef_api.members import invitations, service
from sef_api.models import Invitation, Role

router = APIRouter(prefix="/members", tags=["members"])
invitations_router = APIRouter(prefix="/invitations", tags=["members"])

Session = Annotated[AsyncSession, Depends(get_session)]
CanRead = Annotated[Principal, Depends(require(Permission.MEMBERS_READ))]
#: For the endpoints that change the members: checked again under the organization's lock.
CanManage = Annotated[Principal, Depends(require(Permission.MEMBERS_MANAGE, changes_members=True))]
#: Reading what only an owner may see takes no lock.
CanSeeInvitations = Annotated[Principal, Depends(require(Permission.MEMBERS_MANAGE))]

_CHANGE_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {"model": Problem, "description": "No such member."},
    status.HTTP_409_CONFLICT: {"model": Problem, "description": "It is the last owner."},
}


class MemberOut(BaseModel):
    user: UserOut
    role: Role
    joined_at: datetime


class RoleChange(BaseModel):
    role: Role = Field(description="The member's new role.")


def _out(member: service.Member) -> MemberOut:
    return MemberOut(
        user=UserOut(id=member.user.id, email=member.user.email),
        role=member.role,
        joined_at=member.joined_at,
    )


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "no such member in this organization")


def _last_owner() -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, "an organization keeps at least one owner")


@router.get(
    "",
    summary="List the members",
    description="The members of the caller's organization and their roles, by e-mail address.",
)
async def list_members(caller: CanRead, session: Session) -> list[MemberOut]:
    return [_out(member) for member in await service.list_members(session, caller.organization_id)]


@router.patch(
    "/{user_id}",
    summary="Change a member's role",
    description="Takes effect at once, on the member's next request. The last owner keeps the "
    "role.",
    responses=_CHANGE_RESPONSES,
)
async def change_role(
    user_id: uuid.UUID, body: RoleChange, caller: CanManage, session: Session
) -> MemberOut:
    try:
        member = await service.change_role(session, caller.organization_id, user_id, body.role)
    except service.MemberNotFoundError:
        raise _not_found() from None
    except service.LastOwnerError:
        raise _last_owner() from None
    return _out(member)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a member",
    description="Ends the member's sessions in this organization; their account remains. The "
    "last owner cannot be removed.",
    responses=_CHANGE_RESPONSES,
)
async def remove(user_id: uuid.UUID, caller: CanManage, session: Session) -> None:
    try:
        await service.remove(session, caller.organization_id, user_id)
    except service.MemberNotFoundError:
        raise _not_found() from None
    except service.LastOwnerError:
        raise _last_owner() from None


# --- invitations -------------------------------------------------------------------------------


class InvitationRequest(BaseModel):
    email: EmailStr = Field(description="The address of the person to invite.")
    role: Role = Field(description="The role the person will have.")


class InvitationOut(BaseModel):
    id: uuid.UUID
    email: str
    role: Role
    invited_by: uuid.UUID | None = Field(description="The member who invited, while they exist.")
    created_at: datetime
    expires_at: datetime


class IssuedInvitation(InvitationOut):
    code: str = Field(
        description="Shown this once: give it to the person, who joins with "
        "`POST /auth/accept-invitation`."
    )


def _invitation(invitation: Invitation) -> InvitationOut:
    return InvitationOut(
        id=invitation.id,
        email=invitation.email,
        role=invitation.role,
        invited_by=invitation.invited_by,
        created_at=invitation.created_at,
        expires_at=invitation.expires_at,
    )


@invitations_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Invite a person",
    description="Creates an invitation valid for seven days and returns its code once. An open "
    "invitation for the same address is replaced.",
    dependencies=[NO_STORE],
    responses={status.HTTP_409_CONFLICT: {"model": Problem, "description": "Already a member."}},
)
async def invite(body: InvitationRequest, caller: CanManage, session: Session) -> IssuedInvitation:
    try:
        issued = await invitations.invite(
            session, caller.organization_id, caller.user_id, email=body.email, role=body.role
        )
    except invitations.AlreadyAMemberError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "the address belongs to a member of this organization"
        ) from None
    return IssuedInvitation(**_invitation(issued.invitation).model_dump(), code=issued.code)


@invitations_router.get(
    "",
    summary="List the open invitations",
    description="The invitations that can still be accepted, the newest first; without codes.",
)
async def list_invitations(caller: CanSeeInvitations, session: Session) -> list[InvitationOut]:
    return [
        _invitation(invitation)
        for invitation in await invitations.list_open(session, caller.organization_id)
    ]


@invitations_router.delete(
    "/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an invitation",
    description="Its code stops working. Revoking a revoked or expired invitation changes nothing.",
    responses={
        status.HTTP_404_NOT_FOUND: {"model": Problem, "description": "No such invitation."},
        status.HTTP_409_CONFLICT: {"model": Problem, "description": "Accepted already."},
    },
)
async def revoke(invitation_id: uuid.UUID, caller: CanManage, session: Session) -> None:
    try:
        await invitations.revoke(session, caller.organization_id, invitation_id)
    except invitations.InvitationNotFoundError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "no such invitation in this organization"
        ) from None
    except invitations.InvitationAcceptedError:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "the invitation has been accepted; remove the member instead",
        ) from None
