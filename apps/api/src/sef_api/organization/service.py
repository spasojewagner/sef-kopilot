"""The caller's organization on the database, and the period for which it keeps its stored
invoices.

Setting the period takes the organization's lock, which changes of its members take too, and
checks the caller's permission again under it: an owner whose role changes while the request
waits changes nothing. A change of the period is committed with the audit event that records it,
with what the period was.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api import audit
from sef_api.auth.dependencies import Principal, check_again
from sef_api.auth.permissions import Permission
from sef_api.locks import lock_organization
from sef_api.models import AuditAction, Organization

__all__ = ["find", "set_invoice_retention"]


async def find(session: AsyncSession, organization_id: uuid.UUID) -> Organization:
    """The organization, which exists while a caller is a member of it."""
    return (
        await session.scalars(select(Organization).where(Organization.id == organization_id))
    ).one()


async def set_invoice_retention(
    session: AsyncSession, caller: Principal, days: int | None
) -> Organization:
    """Keep the caller's organization's stored invoices ``days`` after they were stored, or
    every one until a member deletes it with None, and commit. 403 for a caller who no longer
    holds the permission, as :func:`~sef_api.auth.dependencies.require` answers."""
    await lock_organization(session, caller.organization_id)
    permitted = await check_again(session, caller, Permission.ORGANIZATION_MANAGE)
    organization = await find(session, permitted.organization_id)
    before = organization.invoice_retention_days
    if days != before:
        organization.invoice_retention_days = days
        audit.record(
            session,
            permitted,
            AuditAction.ORGANIZATION_RETENTION_SET,
            detail={"from": before, "to": days},
        )
    await session.commit()
    return organization
