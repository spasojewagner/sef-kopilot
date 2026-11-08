"""``/organization``: the caller's organization, how long it keeps its stored invoices, and its
key to SEF, which is set and removed here and never shown (ADR-0050)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.auth.dependencies import Principal, require
from sef_api.auth.permissions import Permission
from sef_api.auth.routes import Problem
from sef_api.db import get_session
from sef_api.models import Organization
from sef_api.organization import service
from sef_api.sef.keys import Keyring

router = APIRouter(prefix="/organization", tags=["organization"])

Session = Annotated[AsyncSession, Depends(get_session)]
CanRead = Annotated[Principal, Depends(require(Permission.ORGANIZATION_READ))]
#: Checked again under the organization's lock by the change itself.
CanManage = Annotated[Principal, Depends(require(Permission.ORGANIZATION_MANAGE))]


class OrganizationSettings(BaseModel):
    id: uuid.UUID
    name: str
    invoice_retention_days: int | None = Field(
        description="How many days after it was stored an invoice is kept before it is deleted, "
        "with its report and its repairs; null when every invoice is kept until a member "
        "deletes it."
    )
    sef_key_set_at: datetime | None = Field(
        description="When an owner set the organization's API key to SEF; null when it has "
        "none. The key itself is never shown."
    )


class OrganizationChange(BaseModel):
    """What to change; what is left out stays as it is."""

    model_config = ConfigDict(extra="forbid")

    invoice_retention_days: int | None = Field(
        default=None,
        ge=1,
        le=3650,
        description="Keep each stored invoice this many days after it was stored, from 1 to "
        "3 650; null to keep every invoice until a member deletes it.",
    )


class SefKeyChange(BaseModel):
    """The organization's API key to SEF, which replaces the one it had."""

    api_key: SecretStr = Field(
        description=(
            "The API key that SEF generated in its settings (API management), 8 to 200 visible "
            "ASCII characters without spaces; spaces around it are left out. It is sealed, and "
            "never shown again."
        ),
    )


class SefKeyState(BaseModel):
    set_at: datetime = Field(description="When the key was set.")


#: The characters a key may hold: it travels in an HTTP header, where only visible ASCII is safe.
_VISIBLE_ASCII = frozenset(chr(code) for code in range(0x21, 0x7F))
#: The lengths a key may have, which leave room for any SEF may generate.
SHORTEST_KEY, LONGEST_KEY = 8, 200


def _checked(api_key: SecretStr) -> SecretStr:
    """``api_key`` without the spaces around it; 422 for one that is no key, saying why and
    never what was sent."""
    key = api_key.get_secret_value().strip()
    if not SHORTEST_KEY <= len(key) <= LONGEST_KEY or not _VISIBLE_ASCII.issuperset(key):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            [
                {
                    "type": "value_error",
                    "loc": ["body", "api_key"],
                    "msg": "a SEF API key is 8 to 200 visible ASCII characters without spaces",
                }
            ],
        )
    return SecretStr(key)


def _keyring(request: Request) -> Keyring:
    """The application's keyring; 503 without ``SEF_FERNET_KEY``."""
    keyring: Keyring | None = request.app.state.sef_keys
    if keyring is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "SEF keys cannot be set on this server: SEF_FERNET_KEY is not set",
        )
    return keyring


async def _out(session: AsyncSession, organization: Organization) -> OrganizationSettings:
    return OrganizationSettings(
        id=organization.id,
        name=organization.name,
        invoice_retention_days=organization.invoice_retention_days,
        sef_key_set_at=await service.sef_key_set_at(session, organization.id),
    )


@router.get(
    "",
    summary="See the organization",
    description=(
        "The caller's organization: its name, how long it keeps its stored invoices, and since "
        "when it has an API key to SEF, if it has one."
    ),
)
async def show(caller: CanRead, session: Session) -> OrganizationSettings:
    return await _out(session, await service.find(session, caller.organization_id))


@router.patch(
    "",
    summary="Change the organization's settings",
    description=(
        "With `invoice_retention_days`, each stored invoice is kept that many days after it was "
        "stored: once it is older, it is deleted, with its report and its repairs, when the API "
        "next deletes what is past its retention, which it does when it starts and every six "
        "hours, or each worker when it starts and every day (ADR-0038). That cannot be undone. "
        "Null keeps every invoice until a member deletes it. The audit log records each change "
        "of the period, with what it was."
    ),
)
async def change(
    body: OrganizationChange, caller: CanManage, session: Session
) -> OrganizationSettings:
    if "invoice_retention_days" not in body.model_fields_set:
        return await _out(session, await service.find(session, caller.organization_id))
    organization = await service.set_invoice_retention(session, caller, body.invoice_retention_days)
    return await _out(session, organization)


@router.put(
    "/sef-key",
    summary="Set the organization's API key to SEF",
    description=(
        "The key that SEF generated in its settings (API management), with which this server "
        "sends the organization's invoices to SEF and asks about them. It replaces the key the "
        "organization had, is sealed with Fernet under `SEF_FERNET_KEY` (ADR-0050), and is "
        "never shown again, logged or reported; the audit log records who set it. An owner, "
        "signed in, sets it: no API key or MCP client may."
    ),
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": Problem,
            "description": "This server cannot keep SEF keys (`SEF_FERNET_KEY`).",
        },
    },
)
async def set_sef_key(
    body: SefKeyChange,
    caller: CanManage,
    session: Session,
    keyring: Annotated[Keyring, Depends(_keyring)],
) -> SefKeyState:
    set_at = await service.set_sef_key(session, caller, keyring, _checked(body.api_key))
    return SefKeyState(set_at=set_at)


@router.delete(
    "/sef-key",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove the organization's API key to SEF",
    description=(
        "Nothing is sent to SEF for the organization until an owner sets a key again. Removing "
        "a key the organization does not have changes nothing. The audit log records who "
        "removed it. SEF's own key stays as it is: revoke it in SEF's settings."
    ),
)
async def remove_sef_key(caller: CanManage, session: Session) -> None:
    await service.remove_sef_key(session, caller)
