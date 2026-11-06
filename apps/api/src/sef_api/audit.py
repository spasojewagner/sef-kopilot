"""The audit log: what was done in an organization that it must be able to account for
(ADR-0024).

An event says what was done, when, by which member and with which API key, to which invoice and
repair. It is added in the transaction of the change it records, so that the two are committed
together or not at all, and it is never changed afterwards. It holds no invoice content:
digests, counts, and the places patches name with what became of them, never a value or a
reason, which may quote the invoice.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.auth.dependencies import Principal
from sef_api.models import AuditAction, AuditEvent

__all__ = ["record"]


def record(
    session: AsyncSession,
    caller: Principal,
    action: AuditAction,
    *,
    invoice_id: uuid.UUID | None = None,
    repair_id: uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Add the event that ``caller`` did ``action``, to be committed with the change itself."""
    session.add(
        AuditEvent(
            organization_id=caller.organization_id,
            actor=caller.user_id,
            key_id=None if caller.key is None else caller.key.key_id,
            action=action,
            invoice_id=invoice_id,
            repair_id=repair_id,
            detail=detail or {},
        )
    )
