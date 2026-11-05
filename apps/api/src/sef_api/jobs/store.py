"""The jobs an organization's members may see, and finding one of them."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.models import Job

__all__ = ["Scope", "find"]


@dataclass(frozen=True)
class Scope:
    """The jobs a caller may see: the organization's, or only those started by
    ``submitted_by``."""

    organization_id: uuid.UUID
    submitted_by: uuid.UUID | None = None

    def holds(self) -> ColumnElement[bool]:
        own = Job.organization_id == self.organization_id
        if self.submitted_by is None:
            return own
        return own & (Job.submitted_by == self.submitted_by)


async def find(session: AsyncSession, scope: Scope, job_id: uuid.UUID) -> Job | None:
    """The job with ``job_id`` in ``scope``; None for any other, so that a job outside the
    scope and one that does not exist look the same."""
    found: Job | None = await session.scalar(select(Job).where(scope.holds(), Job.id == job_id))
    return found
