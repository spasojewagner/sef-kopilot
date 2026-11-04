"""``/members``: the members of the caller's organization and their roles."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.auth.dependencies import Principal, require
from sef_api.auth.permissions import Permission
from sef_api.auth.routes import Problem, UserOut
from sef_api.db import get_session
from sef_api.members import service
from sef_api.models import Role

router = APIRouter(prefix="/members", tags=["members"])

Session = Annotated[AsyncSession, Depends(get_session)]
CanRead = Annotated[Principal, Depends(require(Permission.MEMBERS_READ))]
#: For the endpoints that change the members: checked again under the organization's lock.
CanManage = Annotated[Principal, Depends(require(Permission.MEMBERS_MANAGE, changes_members=True))]

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
