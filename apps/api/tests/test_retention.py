"""What is deleted after its retention period: finished jobs, never one under way (ADR-0038)."""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from sef_api import retention
from sef_api.db import Database
from sef_api.main import create_app
from sef_api.models import Job, JobStatus, Role
from sef_api.settings import Settings

from . import factories
from .conftest import UNREACHABLE_DATABASE, settings_for

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


async def jobs_of_every_age(
    database: Database, now: datetime = NOW, *, under_way: bool = True
) -> dict[str, uuid.UUID]:
    """Finished jobs on either side of 30 days before ``now``, and unless told otherwise two jobs
    under way that started long before it, of two members (a member has one job of a kind under
    way at most); committed."""

    def days_ago(days: float) -> datetime:
        return now - timedelta(days=days)

    async with database.sessions() as session:
        primer = await factories.organization(session, "Primer")
        ana = await factories.person(session, "ana@primer.example")
        bora = await factories.person(session, "bora@primer.example")
        await factories.join(session, primer, ana, Role.OWNER)
        await factories.join(session, primer, bora, Role.ACCOUNTANT)
        finished = {"status": JobStatus.SUCCEEDED, "created_at": days_ago(45)}
        jobs = {
            "succeeded 31 days ago": await factories.job(
                session, primer, ana, **finished, finished_at=days_ago(31)
            ),
            "failed 40 days ago": await factories.job(
                session,
                primer,
                ana,
                status=JobStatus.FAILED,
                error="a reason",
                created_at=days_ago(45),
                finished_at=days_ago(40),
            ),
            "succeeded 29 days ago": await factories.job(
                session, primer, ana, **finished, finished_at=days_ago(29)
            ),
        }
        if under_way:
            jobs["running for 40 days"] = await factories.job(
                session,
                primer,
                ana,
                status=JobStatus.RUNNING,
                created_at=days_ago(40),
                started_at=days_ago(40),
            )
            jobs["queued 40 days ago"] = await factories.job(
                session, primer, bora, created_at=days_ago(40)
            )
        await session.commit()
        return {name: job.id for name, job in jobs.items()}


async def kept(database: Database, jobs: dict[str, uuid.UUID]) -> set[str]:
    async with database.sessions() as session:
        remaining = set(await session.scalars(select(Job.id)))
    return {name for name, job_id in jobs.items() if job_id in remaining}


async def test_finished_jobs_older_than_the_period_are_deleted_and_no_job_under_way(
    committed_database: Database,
) -> None:
    jobs = await jobs_of_every_age(committed_database)

    forgotten = await retention.forget_old_jobs(committed_database, 30, now=NOW)

    assert forgotten == 2
    assert await kept(committed_database, jobs) == {
        "succeeded 29 days ago",
        "running for 40 days",
        "queued 40 days ago",
    }


async def test_the_api_deletes_them_when_it_starts(
    database_url: str, committed_database: Database
) -> None:
    # No job under way, which the start would run again.
    jobs = await jobs_of_every_age(committed_database, datetime.now(UTC), under_way=False)
    app = create_app(settings_for(database_url))

    async with app.router.lifespan_context(app):
        for _ in range(100):
            if await kept(committed_database, jobs) != set(jobs):
                break
            await asyncio.sleep(0.05)

    assert await kept(committed_database, jobs) == {"succeeded 29 days ago"}


async def test_a_deletion_that_fails_is_logged_by_its_kind_and_tried_again(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(retention, "FORGET_EVERY_SECONDS", 0.01)
    database = Database.connect(UNREACHABLE_DATABASE, pooled=False)
    caplog.set_level(logging.WARNING, logger=retention.__name__)

    forgetting = asyncio.create_task(retention.keep_forgetting_old_jobs(database, 30))
    for _ in range(200):
        if len(caplog.records) >= 2:
            break
        await asyncio.sleep(0.05)
    forgetting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await forgetting
    await database.engine.dispose()

    assert len(caplog.records) >= 2
    for record in caplog.records:
        # the kind of the error alone: no address, no message of the driver
        assert re.fullmatch(r"the old finished jobs were not deleted: \w+", record.getMessage())


def test_the_period_is_thirty_days_unless_set_and_at_least_one() -> None:
    assert settings_for().job_retention_days == 30
    assert settings_for(SEF_JOB_RETENTION_DAYS="7").job_retention_days == 7
    with pytest.raises(ValidationError, match="SEF_JOB_RETENTION_DAYS"):
        Settings.from_values({"SEF_ENVIRONMENT": "test", "SEF_JOB_RETENTION_DAYS": "0"})
