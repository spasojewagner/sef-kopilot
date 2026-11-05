"""``/jobs``: the work done in the background for the caller's organization, and how far it has
come, read at once or followed as server-sent events (ADR-0019).

A stream of events watches the job's ``version``, which grows with every change: it reads the
job once a second, each time in a short session of its own, and sends it when the version has
grown. It holds no database connection while it waits, and it ends when the job has finished
or after :data:`STREAM_SECONDS`; a client then reconnects with ``Last-Event-ID``, and is
authorized again.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.auth.dependencies import Principal, require
from sef_api.auth.permissions import Permission
from sef_api.auth.routes import Problem
from sef_api.db import Database, get_database, get_session
from sef_api.jobs import store
from sef_api.models import Job, JobKind, JobStatus

router = APIRouter(prefix="/jobs", tags=["jobs"])

#: Seconds between two readings of a job that a stream follows.
POLL_SECONDS: Final = 1.0
#: Seconds a stream lasts at most, so that a caller who loses access stops seeing the job.
STREAM_SECONDS: Final = 300.0
#: How a job ends.
_FINISHED: Final = frozenset({JobStatus.SUCCEEDED, JobStatus.FAILED})

Session = Annotated[AsyncSession, Depends(get_session)]
#: Every kind of job there is works on invoices.
CanFollow = Annotated[Principal, Depends(require(Permission.INVOICES_SUBMIT))]

_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {"model": Problem, "description": "No such job."}
}
_EVENTS: dict[int | str, dict[str, Any]] = {
    status.HTTP_200_OK: {"description": "A `job` event whenever the job changes."},
    # A stream's errors come before it begins, as JSON.
    status.HTTP_404_NOT_FOUND: {
        "description": "No such job.",
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Problem"}}},
    },
}


class JobOut(BaseModel):
    id: uuid.UUID
    kind: JobKind
    status: JobStatus
    submitted_by: uuid.UUID | None = Field(description="The member who started the job.")
    created_at: datetime
    started_at: datetime | None = Field(description="When a worker first took the job on.")
    finished_at: datetime | None
    progress: dict[str, Any] = Field(description="How far the job has come, as its kind tells.")
    result: dict[str, Any] | None = Field(description="What the job came to, once it succeeded.")
    error: str | None = Field(description="Why the job failed, if it did.")
    version: int = Field(description="Grows with every change to the job.")


def job_out(job: Job) -> JobOut:
    return JobOut(
        id=job.id,
        kind=JobKind(job.kind),
        status=JobStatus(job.status),
        submitted_by=job.submitted_by,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        progress=job.progress,
        result=job.result,
        error=job.error,
        version=job.version,
    )


def scope(caller: Principal) -> store.Scope:
    """The jobs ``caller`` may see: every job of the organization with ``invoices:manage``,
    otherwise the ones they started, as for invoices."""
    if caller.may(Permission.INVOICES_MANAGE):
        return store.Scope(caller.organization_id)
    return store.Scope(caller.organization_id, submitted_by=caller.user_id)


def not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "no such job in this organization")


@dataclass(frozen=True)
class Followed:
    """A job a stream follows, and the scope in which the caller saw it."""

    scope: store.Scope
    job_id: uuid.UUID


async def followed(
    job_id: uuid.UUID, response: Response, caller: CanFollow, session: Session
) -> Followed:
    """The job, if the caller may see it: decided before the stream begins, so that a job they
    may not see is a 404 and not an empty stream."""
    job = await store.find(session, scope(caller), job_id)
    if job is None:
        raise not_found()
    # Added to the stream's own no-cache: no cache keeps a copy of the job.
    response.headers["Cache-Control"] = "no-store"
    # The request's session lasts as long as the stream. Ending its transaction gives its
    # connection back to the pool; the stream reads the job in sessions of its own.
    await session.commit()
    return Followed(scope(caller), job.id)


@router.get(
    "/{job_id}/events",
    response_class=EventSourceResponse,
    summary="Follow a job",
    description=(
        "Server-sent events: a `job` event with the job as `GET /jobs/{job_id}` reads it, at "
        "once and whenever the job changes. Each event's `id` is the job's `version`: a client "
        "that reconnects with `Last-Event-ID` is sent only what changed after it. The stream "
        "ends with the event of the finished job, or after five minutes, when the client "
        "reconnects. Comments keep a quiet stream open. A browser's `EventSource` cannot send "
        "an `Authorization` header: read the stream with `fetch`."
    ),
    responses=_EVENTS,
)
async def follow_job(
    job: Annotated[Followed, Depends(followed)],
    database: Annotated[Database, Depends(get_database)],
    last_event_id: Annotated[
        int | None,
        Header(
            alias="Last-Event-ID",
            ge=0,
            description="The `id` of the last event the client received.",
        ),
    ] = None,
) -> AsyncIterator[ServerSentEvent]:
    sent = -1 if last_event_id is None else last_event_id
    deadline = asyncio.get_running_loop().time() + STREAM_SECONDS
    while True:
        async with database.sessions() as session:
            current = await store.find(session, job.scope, job.job_id)
        if current is None:  # gone with its organization, or no longer the caller's
            return
        if current.version > sent:
            yield ServerSentEvent(data=job_out(current), event="job", id=str(current.version))
            sent = current.version
        if current.status in _FINISHED or asyncio.get_running_loop().time() >= deadline:
            return
        await asyncio.sleep(POLL_SECONDS)


@router.get(
    "/{job_id}",
    summary="Read a job",
    description="Where the job is, how far it has come and, once it has finished, how it ended.",
    responses=_NOT_FOUND,
)
async def read_job(
    job_id: uuid.UUID, response: Response, caller: CanFollow, session: Session
) -> JobOut:
    job = await store.find(session, scope(caller), job_id)
    if job is None:
        raise not_found()
    response.headers["Cache-Control"] = "no-store"
    return job_out(job)
