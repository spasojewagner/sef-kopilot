"""Starting jobs, the jobs an organization's members may see, and the jobs to run again."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.models import UNFINISHED, Job, JobKind

__all__ = ["Scope", "find", "forget_finished", "start", "under_way", "unfinished"]


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


async def start(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    submitted_by: uuid.UUID,
    kind: JobKind,
    parameters: dict[str, Any],
) -> Job | None:
    """Add a job that waits, and commit; None, adding nothing, when the member already has a
    job of the kind under way (:func:`under_way` finds it).

    The table's partial unique index decides, so that two requests at once cannot both add one.
    """
    job: Job | None = await session.scalar(
        insert(Job)
        .values(
            organization_id=organization_id,
            submitted_by=submitted_by,
            kind=kind,
            parameters=parameters,
        )
        .on_conflict_do_nothing(
            index_elements=["organization_id", "submitted_by", "kind"],
            index_where=text("status IN ('queued', 'running')"),
        )
        .returning(Job)
    )
    await session.commit()
    return job


async def under_way(
    session: AsyncSession, organization_id: uuid.UUID, submitted_by: uuid.UUID, kind: JobKind
) -> Job | None:
    """The member's job of the kind that has not finished, if there is one."""
    found: Job | None = await session.scalar(
        select(Job).where(
            Job.organization_id == organization_id,
            Job.submitted_by == submitted_by,
            Job.kind == kind,
            Job.status.in_(UNFINISHED),
        )
    )
    return found


async def unfinished(session: AsyncSession) -> list[uuid.UUID]:
    """Every job, of every organization, that has not finished: the oldest first."""
    found = await session.scalars(
        select(Job.id).where(Job.status.in_(UNFINISHED)).order_by(Job.created_at, Job.id)
    )
    return list(found)


async def find(session: AsyncSession, scope: Scope, job_id: uuid.UUID) -> Job | None:
    """The job with ``job_id`` in ``scope``; None for any other, so that a job outside the
    scope and one that does not exist look the same."""
    found: Job | None = await session.scalar(select(Job).where(scope.holds(), Job.id == job_id))
    return found


async def forget_finished(session: AsyncSession, *, before: datetime) -> int:
    """Delete every job, of every organization, that finished before ``before``, and commit; how
    many. A job under way has no end yet, so it is never deleted, however old it is."""
    deleted = await session.scalars(delete(Job).where(Job.finished_at < before).returning(Job.id))
    count = len(deleted.all())
    await session.commit()
    return count
