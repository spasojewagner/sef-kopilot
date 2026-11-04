"""``/api-keys``: the keys with which machine clients act for a member of the organization."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import AwareDatetime, BaseModel, Field, StringConstraints, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.api_keys import service
from sef_api.auth.dependencies import Principal, require
from sef_api.auth.permissions import Permission
from sef_api.auth.routes import NO_STORE, Problem
from sef_api.db import get_session
from sef_api.models import ApiKey

router = APIRouter(prefix="/api-keys", tags=["api keys"])

Session = Annotated[AsyncSession, Depends(get_session)]
CanIssue = Annotated[Principal, Depends(require(Permission.API_KEYS_ISSUE))]

#: The permissions a key may hold (``KEY_PERMISSIONS``), as the API spells them.
KeyPermission = Literal["invoices:validate", "invoices:submit", "invoices:manage"]
KeyName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class KeyRequest(BaseModel):
    name: KeyName = Field(description="What the key is for, such as the ERP that uses it.")
    permissions: set[KeyPermission] = Field(
        min_length=1,
        description="What the key allows: permissions the caller's role grants, among those a "
        "key may hold.",
    )
    expires_at: AwareDatetime | None = Field(
        default=None, description="When the key stops working, in the future; never when null."
    )

    @field_validator("expires_at")
    @classmethod
    def _in_the_future(cls, value: datetime | None) -> datetime | None:
        if value is not None and value <= datetime.now(UTC):
            raise ValueError("an expiry must be in the future")
        return value


class KeyOut(BaseModel):
    id: uuid.UUID
    name: str
    prefix: str = Field(description="The key's first characters, to tell it apart; not the key.")
    permissions: list[Permission]
    acts_for: uuid.UUID = Field(description="The member for whom the key acts.")
    created_at: datetime
    expires_at: datetime | None = Field(description="When the key stops working; null if never.")


class IssuedKey(KeyOut):
    key: str = Field(
        description="Shown this once: the machine client sends it as `Authorization: Bearer <key>`."
    )


def _scope(caller: Principal) -> service.Scope:
    """The keys ``caller`` may see and revoke: every key of the organization with
    ``api_keys:manage``, otherwise their own."""
    if caller.may(Permission.API_KEYS_MANAGE):
        return service.Scope(caller.organization_id)
    return service.Scope(caller.organization_id, user_id=caller.user_id)


def _key(key: ApiKey) -> KeyOut:
    return KeyOut(
        id=key.id,
        name=key.name,
        prefix=key.prefix,
        permissions=[Permission(permission) for permission in key.permissions],
        acts_for=key.user_id,
        created_at=key.created_at,
        expires_at=key.expires_at,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Issue an API key",
    description=(
        "Issues a key with which a machine client, such as an ERP, acts for the caller with "
        "some of their permissions, and returns it this once. What the key allows is checked "
        "again on every request against the caller's role at that moment. A key cannot be "
        "used to issue keys."
    ),
    dependencies=[NO_STORE],
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": Problem,
            "description": "The caller's role does not grant a permission the key was to hold.",
        },
        status.HTTP_409_CONFLICT: {
            "model": Problem,
            "description": "The caller has as many keys as a member may.",
        },
    },
)
async def issue_key(body: KeyRequest, caller: CanIssue, session: Session) -> IssuedKey:
    try:
        issued = await service.issue(
            session,
            organization_id=caller.organization_id,
            user_id=caller.user_id,
            role=caller.role,
            name=body.name,
            permissions=map(Permission, body.permissions),
            expires_at=body.expires_at,
        )
    except service.NotGrantedError as error:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"your role does not grant {error.permission}"
        ) from None
    except service.TooManyKeysError:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"a member has at most {service.MAX_KEYS_PER_MEMBER} API keys; revoke one first",
        ) from None
    return IssuedKey(**_key(issued.key).model_dump(), key=issued.secret)


@router.get(
    "",
    summary="List API keys",
    description=(
        "The keys that work, the newest first, without the keys themselves: the caller's own, "
        "or with `api_keys:manage` every key of the organization."
    ),
)
async def list_keys(caller: CanIssue, session: Session) -> list[KeyOut]:
    return [_key(key) for key in await service.keys_in(session, _scope(caller))]


@router.delete(
    "/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an API key",
    description=(
        "The key stops working at once. The caller revokes their own keys, or with "
        "`api_keys:manage` any key of the organization. Revoking a key that works no longer "
        "changes nothing."
    ),
    responses={status.HTTP_404_NOT_FOUND: {"model": Problem, "description": "No such key."}},
)
async def revoke_key(key_id: uuid.UUID, caller: CanIssue, session: Session) -> None:
    if not await service.revoke(session, _scope(caller), key_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such API key in this organization")
