"""The caller's organization on the database: the period for which it keeps its stored
invoices, and its key to SEF.

Setting the period or the key takes the organization's lock, which changes of its members take
too, and checks the caller's permission again under it: an owner whose role changes while the
request waits changes nothing. Each change is committed with the audit event that records it:
what the period was, and whether a key was replaced, never the key (ADR-0050).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import SecretStr
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api import audit
from sef_api.auth.dependencies import Principal, check_again
from sef_api.auth.permissions import Permission
from sef_api.locks import lock_organization
from sef_api.logs import security_event
from sef_api.models import AuditAction, Organization, SefKey
from sef_api.sef.keys import Keyring

__all__ = ["find", "remove_sef_key", "sef_key_set_at", "set_invoice_retention", "set_sef_key"]


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


async def sef_key_set_at(session: AsyncSession, organization_id: uuid.UUID) -> datetime | None:
    """When the organization's SEF key was set; None when it has none."""
    return await session.scalar(
        select(SefKey.set_at).where(SefKey.organization_id == organization_id)
    )


async def set_sef_key(
    session: AsyncSession, caller: Principal, keyring: Keyring, api_key: SecretStr
) -> datetime:
    """Seal ``api_key`` as the caller's organization's key to SEF, in place of the one it had,
    and commit; when it was set. 403 for a caller who no longer holds the permission."""
    await lock_organization(session, caller.organization_id)
    permitted = await check_again(session, caller, Permission.ORGANIZATION_MANAGE)
    organization_id = permitted.organization_id
    replaced = await sef_key_set_at(session, organization_id) is not None
    token = keyring.seal(organization_id, api_key)
    stored = await session.execute(
        insert(SefKey)
        .values(organization_id=organization_id, token=token)
        .on_conflict_do_update(
            index_elements=[SefKey.organization_id], set_={"token": token, "set_at": func.now()}
        )
        .returning(SefKey.set_at)
    )
    set_at: datetime = stored.scalar_one()
    audit.record(session, permitted, AuditAction.SEF_KEY_SET, detail={"replaced": replaced})
    await session.commit()
    security_event(
        "sef-key.set",
        organization=str(organization_id),
        user=str(permitted.user_id),
        replaced=replaced,
    )
    return set_at


async def remove_sef_key(session: AsyncSession, caller: Principal) -> None:
    """Remove the caller's organization's key to SEF, if it has one, and commit. 403 for a
    caller who no longer holds the permission."""
    await lock_organization(session, caller.organization_id)
    permitted = await check_again(session, caller, Permission.ORGANIZATION_MANAGE)
    removed = await session.scalar(
        delete(SefKey)
        .where(SefKey.organization_id == permitted.organization_id)
        .returning(SefKey.organization_id)
    )
    if removed is None:
        return
    audit.record(session, permitted, AuditAction.SEF_KEY_REMOVED)
    await session.commit()
    security_event("sef-key.removed", organization=str(removed), user=str(permitted.user_id))
