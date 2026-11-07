"""Jobs through Redis (``SEF_JOBS=arq``): the API puts them on the queue, a worker runs them, and
its sweep puts on the queue the unfinished jobs that are not there.

The tests that need Redis run on the server named by ``SEF_TEST_REDIS_URL``, whose database
they empty, and are skipped without it.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import sys
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from arq.connections import ArqRedis, create_pool
from arq.worker import Worker
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from sef_api.db import Database
from sef_api.jobs import worker
from sef_api.jobs.queue import TASK, ArqRunner, redis_settings
from sef_api.jobs.runners import InlineRunner
from sef_api.jobs.runs import Claimed, JobContext, Progress
from sef_api.main import create_app
from sef_api.models import Job, StoredInvoice
from sef_api.settings import Settings

from . import factories
from .conftest import TEST_REDIS_URL, settings_for
from .factories import Office, office
from .test_invoices_validate import VALID, Scripted
from .test_revalidation import NOTHING

#: Nothing listens there.
NO_REDIS = "redis://127.0.0.1:1/0"


@pytest.fixture
async def redis() -> AsyncIterator[ArqRedis]:
    """The test server's Redis database, emptied before and after the test."""
    if not TEST_REDIS_URL:
        pytest.skip("set SEF_TEST_REDIS_URL to a Redis server to run the worker tests")
    if sys.platform == "win32":
        pytest.skip("a worker run by a test stops with SIGUSR1, which Windows does not have")
    pool = await create_pool(redis_settings(TEST_REDIS_URL))
    await pool.flushdb()
    yield pool
    await pool.flushdb()
    await pool.aclose()


@pytest.fixture
async def primer(committed_database: Database) -> Office:
    async with committed_database.sessions() as session:
        created = await office(session, "Primer Računovodstvo", "primer.example")
        await session.commit()
    return created


def through_redis(database_url: str, redis_url: str | None = TEST_REDIS_URL) -> Settings:
    return settings_for(database_url, SEF_JOBS="arq", REDIS_URL=redis_url or NO_REDIS)


async def work(settings: Settings) -> None:
    """Run a worker until the queue is empty, the jobs its sweep at startup puts there included;
    a worker still busy after 30 seconds fails the test.

    The sweep at second 0 of every minute is moved half an hour away. A run that crossed a
    minute would sweep twice, and put back on the queue a job the test leaves unfinished."""
    assert TEST_REDIS_URL is not None
    options = worker.options(settings, TEST_REDIS_URL)
    later = (datetime.now(UTC).minute + 30) % 60
    options["cron_jobs"] = [dataclasses.replace(job, minute=later) for job in options["cron_jobs"]]
    serving = Worker(
        **options,
        burst=True,
        poll_delay=0.01,
        handle_signals=False,
        timezone=UTC,
    )
    try:
        await asyncio.wait_for(serving.async_run(), 30)
    finally:
        for task in serving.tasks.values():
            task.cancel()
        await serving.close()


async def queued(redis: ArqRedis) -> list[tuple[str, tuple[Any, ...]]]:
    return [(job.function, job.args) for job in await redis.queued_jobs()]


async def statuses(database: Database) -> dict[uuid.UUID | None, str]:
    """The status of each member's job."""
    async with database.sessions() as session:
        rows = await session.execute(select(Job.submitted_by, Job.status))
        return dict(rows.all())


async def test_the_api_puts_a_job_on_the_queue_and_a_worker_runs_it(
    committed_database: Database, database_url: str, redis: ArqRedis, primer: Office
) -> None:
    async with committed_database.sessions() as session:
        await factories.stored_invoice(session, primer.organization, primer.client, VALID)
        await session.commit()
    settings = through_redis(database_url)
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api,
    ):
        started = await api.post("/invoices/revalidations", headers=primer.as_owner())
    on_the_queue = await queued(redis)

    await work(settings)

    assert on_the_queue == [(TASK, (started.json()["id"],))]
    async with committed_database.sessions() as session:
        job = await session.scalar(select(Job))
        valid = await session.scalar(select(StoredInvoice.valid))
    assert job is not None
    assert (job.status, job.result) == ("succeeded", NOTHING | {"total": 1, "done": 1, "valid": 1})
    assert valid is True
    assert await queued(redis) == []


async def test_a_job_is_on_the_queue_once_however_often_it_is_put_there(
    redis: ArqRedis,
) -> None:
    assert TEST_REDIS_URL is not None
    runner = ArqRunner(redis_settings(TEST_REDIS_URL))
    job_id = uuid.uuid4()

    try:
        for _ in range(3):
            await runner.enqueue(job_id)
    finally:
        await runner.stop()

    assert await queued(redis) == [(TASK, (str(job_id),))]


async def test_the_sweep_puts_on_the_queue_the_unfinished_jobs_that_are_not_there(
    committed_database: Database,
    database_url: str,
    redis: ArqRedis,
    primer: Office,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A job the API could not put on the queue, and a job whose worker died, run; a finished
    job is left alone."""
    async with committed_database.sessions() as session:
        await factories.job(session, primer.organization, primer.owner)
        await factories.job(
            session, primer.organization, primer.accountant, status="running", attempts=1
        )
        await factories.job(
            session, primer.organization, primer.client, status="failed", finished_at=func.now()
        )
        await session.commit()

    with caplog.at_level(logging.INFO, logger="sef_api.jobs.worker"):
        await work(through_redis(database_url))

    assert await statuses(committed_database) == {
        primer.owner.id: "succeeded",
        primer.accountant.id: "succeeded",
        primer.client.id: "failed",
    }
    assert "the sweep put 2 unfinished jobs on the queue" in caplog.text


async def test_an_attempt_cut_short_is_swept_back_and_the_next_one_continues(
    committed_database: Database,
    database_url: str,
    redis: ArqRedis,
    primer: Office,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first attempt runs past its time; the sweep of the next worker puts the job back on
    the queue, and the second attempt continues from the first one's progress."""

    async def slow_at_first(
        _context: JobContext, job: Claimed, progress: Progress
    ) -> dict[str, Any]:
        if job.attempt == 1:
            await progress.report({"step": 1})
            await asyncio.Event().wait()
        return {"continued from": job.progress}

    monkeypatch.setattr(worker, "ATTEMPT_SECONDS", 0.2)
    monkeypatch.setattr(worker, "HANDLERS", {"revalidation": slow_at_first})
    async with committed_database.sessions() as session:
        await factories.job(session, primer.organization, primer.owner)
        await session.commit()
    settings = through_redis(database_url)

    await work(settings)
    cut_short = await statuses(committed_database)
    await work(settings)

    async with committed_database.sessions() as session:
        job = await session.scalar(select(Job))
    assert job is not None
    assert cut_short == {primer.owner.id: "running"}
    assert (job.status, job.attempts, job.result) == (
        "succeeded",
        2,
        {"continued from": {"step": 1}},
    )


async def test_without_redis_a_job_waits_in_the_database_for_the_sweep(
    committed_database: Database,
    database_url: str,
    primer: Office,
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_app(through_redis(database_url, redis_url=None))

    with caplog.at_level(logging.WARNING, logger="sef_api.jobs.queue"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
            started = await api.post("/invoices/revalidations", headers=primer.as_owner())
    await app.state.jobs.stop()
    await app.state.database.engine.dispose()

    assert (started.status_code, started.json()["status"]) == (202, "queued")
    assert await statuses(committed_database) == {primer.owner.id: "queued"}
    assert f"job {started.json()['id']} was not put on the queue" in caplog.text


async def test_with_redis_the_api_leaves_the_unfinished_jobs_to_the_workers(
    committed_database: Database, database_url: str, redis: ArqRedis, primer: Office
) -> None:
    async with committed_database.sessions() as session:
        await factories.job(session, primer.organization, primer.owner)
        await session.commit()
    app = create_app(through_redis(database_url))

    async with app.router.lifespan_context(app):
        pass

    assert await queued(redis) == []
    assert await statuses(committed_database) == {primer.owner.id: "queued"}


def test_the_settings_say_where_jobs_run() -> None:
    assert isinstance(create_app(settings_for()).state.jobs, InlineRunner)
    assert isinstance(
        create_app(settings_for(SEF_JOBS="arq", REDIS_URL=NO_REDIS)).state.jobs, ArqRunner
    )


async def test_a_worker_whose_validator_cannot_run_starts_and_says_why(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    unavailable = Scripted(problem="rule set 'ubl-2.1' is absent")
    monkeypatch.setattr(worker, "validator_for", lambda _: unavailable)
    ctx: dict[str, Any] = {"settings": settings_for()}

    with caplog.at_level(logging.WARNING, logger="sef_api.jobs.worker"):
        await worker.startup(ctx)
    await worker.shutdown(ctx)

    assert ctx["context"].validator is unavailable
    assert "the validator cannot run: rule set 'ubl-2.1' is absent" in caplog.text


def test_a_worker_serves_the_queue_of_its_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    served: list[dict[str, Any]] = []
    monkeypatch.setattr(worker, "run_worker", served.append)

    worker.main(settings_for(REDIS_URL="redis://queue.example:6380/2"))

    (options,) = served
    assert [function.name for function in options["functions"]] == [TASK]
    assert options["functions"][0].timeout_s == worker.ATTEMPT_SECONDS
    sweeping, forgetting = options["cron_jobs"]
    assert sweeping.name == "cron:sweep"
    # at startup, then at second 0 of every minute (the tests move the latter away)
    assert (sweeping.run_at_startup, sweeping.minute, sweeping.second) == (True, None, 0)
    assert forgetting.name == "cron:forget"
    # at startup, then at 03:17 every day (ADR-0038)
    assert (forgetting.run_at_startup, forgetting.hour, forgetting.minute, forgetting.second) == (
        True,
        {3},
        {17},
        0,
    )
    assert (options["redis_settings"].host, options["redis_settings"].port) == (
        "queue.example",
        6380,
    )


def test_a_worker_without_redis_does_not_start() -> None:
    with pytest.raises(SystemExit, match="REDIS_URL must name the Redis server of the job queue"):
        worker.main(settings_for())
