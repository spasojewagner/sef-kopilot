"""``/organization``: the caller's organization, and how long it keeps its stored invoices."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.auth.dependencies import Principal, require
from sef_api.auth.permissions import Permission
from sef_api.db import get_session
from sef_api.models import Organization
from sef_api.organization import service

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


def _out(organization: Organization) -> OrganizationSettings:
    return OrganizationSettings(
        id=organization.id,
        name=organization.name,
        invoice_retention_days=organization.invoice_retention_days,
    )


@router.get(
    "",
    summary="See the organization",
    description="The caller's organization: its name and how long it keeps its stored invoices.",
)
async def show(caller: CanRead, session: Session) -> OrganizationSettings:
    return _out(await service.find(session, caller.organization_id))


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
        return _out(await service.find(session, caller.organization_id))
    return _out(await service.set_invoice_retention(session, caller, body.invoice_retention_days))
