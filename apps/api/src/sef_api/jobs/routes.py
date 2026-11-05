"""``/jobs``: the work done in the background for the caller's organization, and how far it has
come."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.auth.dependencies import Principal, require
from sef_api.auth.permissions import Permission
from sef_api.auth.routes import Problem
from sef_api.db import get_session
from sef_api.jobs import store
from sef_api.models import Job, JobKind, JobStatus

router = APIRouter(prefix="/jobs", tags=["jobs"])

Session = Annotated[AsyncSession, Depends(get_session)]
#: Every kind of job there is works on invoices.
CanFollow = Annotated[Principal, Depends(require(Permission.INVOICES_SUBMIT))]

_NOT_FOUND: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {"model": Problem, "description": "No such job."}
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
