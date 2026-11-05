"""Running a job: taking it on, reporting how far it has come, and finishing it.

Each step is a transaction on the job's row:

- taking it on makes the job ``running`` and counts one attempt more, from ``queued`` or from
  ``running``, so that a job whose worker died can be taken on again;
- every report of progress, and the end, are written only while the attempt is still the
  latest. A worker that was given up for dead learns at its next report that it was superseded
  (:class:`SupersededError`), and stops without overwriting its successor;
- a job that has finished, or is gone, is left alone.

Running a job twice is therefore safe, provided its work is: each kind's handler does work that
can be done again with the same result.

An attempt sees the progress the attempts before it reported, so that it can continue where
they stopped. A handler that writes its progress in the transaction of the work the progress
counts (``Progress.report(..., session=...)``) makes that exact: the work and its count are
committed together or not at all, so an attempt that continues does no work twice, and a
superseded attempt, whose transaction fails, leaves no work behind.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.db import Database
from sef_api.invoices.validator import Validator
from sef_api.models import UNFINISHED, Job, JobStatus
from sef_api.settings import Settings

__all__ = [
    "Claimed",
    "Handler",
    "JobContext",
    "JobError",
    "Progress",
    "SupersededError",
    "run_job",
]

logger = logging.getLogger(__name__)

#: What a job that failed for no reason it can tell records as its error.
FAILED = "the job could not be completed"


@dataclass(frozen=True)
class JobContext:
    """What a job may use: the database, the validator and the settings of its process."""

    database: Database
    validator: Validator
    settings: Settings


@dataclass(frozen=True)
class Claimed:
    """A job one attempt has taken on: what it works on, when it was started, how far the
    attempts before this one came, and which attempt this is."""

    id: uuid.UUID
    organization_id: uuid.UUID
    submitted_by: uuid.UUID | None
    kind: str
    parameters: dict[str, Any]
    created_at: datetime
    progress: dict[str, Any]
    attempt: int


class JobError(Exception):
    """A job's failure, with a message fit to show the member who started it. Any other
    exception fails the job with :data:`FAILED`, and its type alone is logged."""


class SupersededError(Exception):
    """A later attempt has taken the job on; this attempt must stop writing."""


class Progress:
    """Reports how far one attempt at a job has come, each time in a transaction of its own."""

    def __init__(self, database: Database, job: Claimed) -> None:
        self._database = database
        self._job = job

    async def report(
        self, progress: Mapping[str, Any], *, session: AsyncSession | None = None
    ) -> None:
        """Make ``progress`` the job's progress; raises :class:`SupersededError` when the
        attempt is no longer the latest.

        The progress is written in the transaction of ``session``, which the caller then
        commits with the work the progress counts, or rolls back after the error; without a
        session, in a transaction of its own.
        """
        if session is not None:
            await self._write(session, progress)
            return
        async with self._database.sessions() as own:
            await self._write(own, progress)
            await own.commit()

    async def _write(self, session: AsyncSession, progress: Mapping[str, Any]) -> None:
        changed = await session.execute(
            update(Job)
            .where(_still_mine(self._job))
            .values(progress=dict(progress), version=Job.version + 1)
            .returning(Job.id)
        )
        if changed.one_or_none() is None:
            raise SupersededError


#: What a kind of job does: given the context, the job and its progress, the job's result.
Handler = Callable[[JobContext, Claimed, Progress], Awaitable[dict[str, Any]]]


async def run_job(context: JobContext, job_id: uuid.UUID, handlers: Mapping[str, Handler]) -> None:
    """Take the job on and run it to its end, with the handler of its kind. A job that has
    finished, or is gone, is left alone; one whose attempt is superseded stops quietly."""
    job = await _claim(context.database, job_id)
    if job is None:
        return
    try:
        result = await handlers[job.kind](context, job, Progress(context.database, job))
    except SupersededError:
        logger.info("job %s: attempt %d was superseded", job.id, job.attempt)
        return
    except JobError as error:
        await _finish(context.database, job, JobStatus.FAILED, error=str(error))
        return
    except Exception as error:  # the job's failure is its outcome, not the worker's
        logger.error("job %s failed: %s", job.id, type(error).__name__)
        await _finish(context.database, job, JobStatus.FAILED, error=FAILED)
        return
    await _finish(context.database, job, JobStatus.SUCCEEDED, result=result)


async def _claim(database: Database, job_id: uuid.UUID) -> Claimed | None:
    async with database.sessions() as session:
        row = (
            await session.execute(
                update(Job)
                .where(Job.id == job_id, Job.status.in_(UNFINISHED))
                .values(
                    status=JobStatus.RUNNING,
                    attempts=Job.attempts + 1,
                    version=Job.version + 1,
                    started_at=func.coalesce(Job.started_at, func.now()),
                )
                .returning(
                    Job.id,
                    Job.organization_id,
                    Job.submitted_by,
                    Job.kind,
                    Job.parameters,
                    Job.created_at,
                    Job.progress,
                    Job.attempts,
                )
            )
        ).one_or_none()
        await session.commit()
    return None if row is None else Claimed(*row)


async def _finish(
    database: Database,
    job: Claimed,
    status: JobStatus,
    *,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    async with database.sessions() as session:
        await session.execute(
            update(Job)
            .where(_still_mine(job))
            .values(
                status=status,
                result=result,
                error=error,
                finished_at=func.now(),
                version=Job.version + 1,
            )
        )
        await session.commit()


def _still_mine(job: Claimed) -> Any:
    """The job is running, and this attempt is the latest."""
    return (Job.id == job.id) & (Job.attempts == job.attempt) & (Job.status == JobStatus.RUNNING)
