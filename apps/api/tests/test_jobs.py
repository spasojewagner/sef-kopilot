"""Jobs on PostgreSQL: taking one on, its progress, how it ends, attempts that supersede or
continue each other, the inline runner, and reading and following a job."""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.db import Database
from sef_api.jobs import routes
from sef_api.jobs.runners import InlineRunner
from sef_api.jobs.runs import (
    FAILED,
    Claimed,
    Handler,
    JobContext,
    JobError,
    Progress,
    run_job,
)
from sef_api.main import create_app
from sef_api.models import Job, JobStatus, Organization, Role

from . import factories
from .conftest import settings_for
from .factories import Office, office
from .streams import EventStream
from .test_invoices_validate import Scripted


@pytest.fixture
def context(committed_database: Database) -> JobContext:
    return JobContext(committed_database, Scripted(), settings_for())


async def owned_job(database: Database, **columns: Any) -> tuple[uuid.UUID, dict[str, str]]:
    """A job that waits, of a new organization, started by its owner, and the headers with which
    the owner follows it; committed."""
    async with database.sessions() as session:
        primer = await factories.organization(session, "Primer")
        ana = await factories.person(session, f"ana.{uuid.uuid4().hex[:8]}@primer.example")
        await factories.join(session, primer, ana, Role.OWNER)
        job = await factories.job(session, primer, ana, **columns)
        await session.commit()
        return job.id, factories.bearer(ana, primer, Role.OWNER)


async def waiting_job(database: Database, **columns: Any) -> uuid.UUID:
    """A job that waits, of a new organization, started by its owner; committed."""
    job_id, _ = await owned_job(database, **columns)
    return job_id


async def the_job(database: Database, job_id: uuid.UUID) -> Job:
    async with database.sessions() as session:
        found = await session.scalar(select(Job).where(Job.id == job_id))
        assert found is not None
        return found


def handling(handler: Handler) -> dict[str, Handler]:
    return {"revalidation": handler}


async def counting_to_two(
    _context: JobContext, _job: Claimed, progress: Progress
) -> dict[str, Any]:
    await progress.report({"done": 1, "total": 2})
    await progress.report({"done": 2, "total": 2})
    return {"total": 2}


async def test_a_job_runs_to_its_end_and_tells_how_far_it_has_come(
    context: JobContext,
) -> None:
    job_id = await waiting_job(context.database)

    await run_job(context, job_id, handling(counting_to_two))

    job = await the_job(context.database, job_id)
    assert (job.status, job.progress, job.result, job.error) == (
        "succeeded",
        {"done": 2, "total": 2},
        {"total": 2},
        None,
    )
    assert (job.attempts, job.version) == (1, 4)  # taken on, two reports, finished
    assert job.started_at is not None
    assert job.finished_at is not None


async def test_a_job_that_fails_records_a_message_and_logs_only_the_kind_of_error(
    context: JobContext, caplog: pytest.LogCaptureFixture
) -> None:
    job_id = await waiting_job(context.database)

    async def failing(*_: Any) -> dict[str, Any]:
        raise RuntimeError("<cbc:ID>RF-2026-000124</cbc:ID>")

    with caplog.at_level(logging.INFO):
        await run_job(context, job_id, handling(failing))

    job = await the_job(context.database, job_id)
    assert (job.status, job.error, job.result) == ("failed", FAILED, None)
    assert "RuntimeError" in caplog.text
    assert "RF-2026-000124" not in caplog.text


async def test_a_job_that_fails_for_a_reason_it_can_tell_records_the_reason(
    context: JobContext,
) -> None:
    job_id = await waiting_job(context.database)

    async def unable(*_: Any) -> dict[str, Any]:
        raise JobError("the validator cannot run on this server")

    await run_job(context, job_id, handling(unable))

    job = await the_job(context.database, job_id)
    assert (job.status, job.error) == ("failed", "the validator cannot run on this server")


@pytest.mark.parametrize("status", ["succeeded", "failed"])
async def test_a_finished_job_is_left_alone(context: JobContext, status: str) -> None:
    job_id = await waiting_job(context.database, status=status, finished_at=func.now())
    handled: list[uuid.UUID] = []

    async def noting(_context: JobContext, job: Claimed, _progress: Progress) -> dict[str, Any]:
        handled.append(job.id)
        return {}

    await run_job(context, job_id, handling(noting))
    await run_job(context, uuid.uuid4(), handling(noting))

    job = await the_job(context.database, job_id)
    assert handled == []
    assert (job.status, job.attempts, job.version) == (status, 0, 0)


@pytest.mark.parametrize("first_reports", [True, False], ids=["reporting", "finishing"])
async def test_a_job_taken_on_again_supersedes_the_attempt_before(
    context: JobContext, first_reports: bool
) -> None:
    """The first attempt is given up for dead while it works. The second finishes the job;
    the first, when it wakes, can write neither its progress nor its end."""
    job_id = await waiting_job(context.database)
    first_working, first_may_go_on = asyncio.Event(), asyncio.Event()

    async def slow_first(_context: JobContext, job: Claimed, progress: Progress) -> dict[str, Any]:
        if job.attempt == 1:
            first_working.set()
            await first_may_go_on.wait()
            if first_reports:
                await progress.report({"by": "the first"})
            return {"by": "the first"}
        await progress.report({"by": "the second"})
        return {"by": "the second"}

    first = asyncio.create_task(run_job(context, job_id, handling(slow_first)))
    await asyncio.wait_for(first_working.wait(), 5)
    await run_job(context, job_id, handling(slow_first))
    first_may_go_on.set()
    await first

    job = await the_job(context.database, job_id)
    assert (job.status, job.attempts, job.progress, job.result) == (
        "succeeded",
        2,
        {"by": "the second"},
        {"by": "the second"},
    )


async def test_an_attempt_sees_how_far_the_attempt_before_it_came(context: JobContext) -> None:
    job_id = await waiting_job(context.database)
    seen: list[tuple[dict[str, Any], Any]] = []
    first_reported = asyncio.Event()

    async def continuing(_context: JobContext, job: Claimed, progress: Progress) -> dict[str, Any]:
        seen.append((job.progress, job.created_at))
        if job.attempt == 1:
            await progress.report({"done": 1})
            first_reported.set()
            await asyncio.Event().wait()  # until it is given up for dead
        return {"done": job.progress["done"] + 1}

    first = asyncio.create_task(run_job(context, job_id, handling(continuing)))
    await asyncio.wait_for(first_reported.wait(), 5)
    await run_job(context, job_id, handling(continuing))
    first.cancel()
    await asyncio.gather(first, return_exceptions=True)

    job = await the_job(context.database, job_id)
    assert seen == [({}, job.created_at), ({"done": 1}, job.created_at)]
    assert (job.status, job.result) == ("succeeded", {"done": 2})


async def test_work_written_with_its_progress_is_undone_with_it_when_superseded(
    context: JobContext,
) -> None:
    """The first attempt writes its work and its progress in one transaction after the second
    attempt has finished the job: neither is kept."""
    job_id = await waiting_job(context.database)
    first_working, first_may_go_on = asyncio.Event(), asyncio.Event()

    async def renaming(context: JobContext, job: Claimed, progress: Progress) -> dict[str, Any]:
        if job.attempt == 1:
            first_working.set()
            await first_may_go_on.wait()
        async with context.database.sessions() as session:
            await session.execute(
                update(Organization)
                .where(Organization.id == job.organization_id)
                .values(name=f"renamed by attempt {job.attempt}")
            )
            await progress.report({"renamed by": job.attempt}, session=session)
            await session.commit()
        return {}

    first = asyncio.create_task(run_job(context, job_id, handling(renaming)))
    await asyncio.wait_for(first_working.wait(), 5)
    await run_job(context, job_id, handling(renaming))
    first_may_go_on.set()
    await first

    job = await the_job(context.database, job_id)
    async with context.database.sessions() as session:
        name = await session.scalar(
            select(Organization.name).where(Organization.id == job.organization_id)
        )
    assert (job.status, job.progress, name) == (
        "succeeded",
        {"renamed by": 2},
        "renamed by attempt 2",
    )


async def test_progress_reported_in_a_transaction_is_rolled_back_with_it(
    context: JobContext,
) -> None:
    job_id = await waiting_job(context.database)
    seen_meanwhile: list[dict[str, Any]] = []

    async def undoing(context: JobContext, job: Claimed, progress: Progress) -> dict[str, Any]:
        async with context.database.sessions() as session:
            await progress.report({"done": 1}, session=session)
            seen_meanwhile.append((await the_job(context.database, job.id)).progress)
            await session.rollback()
        return {}

    await run_job(context, job_id, handling(undoing))

    job = await the_job(context.database, job_id)
    assert seen_meanwhile == [{}]
    assert (job.status, job.progress) == ("succeeded", {})


async def test_the_inline_runner_runs_each_job_it_is_given(context: JobContext) -> None:
    jobs = [await waiting_job(context.database) for _ in range(2)]
    runner = InlineRunner(functools.partial(run_job, context, handlers=handling(counting_to_two)))

    for job_id in jobs:
        await runner.enqueue(job_id)
    await runner.drain()

    assert [(await the_job(context.database, job_id)).status for job_id in jobs] == [
        "succeeded",
        "succeeded",
    ]


async def test_a_job_cut_short_when_the_runner_stops_stays_unfinished(
    context: JobContext,
) -> None:
    job_id = await waiting_job(context.database)
    working = asyncio.Event()

    async def endless(*_: Any) -> dict[str, Any]:
        working.set()
        await asyncio.Event().wait()
        return {}

    runner = InlineRunner(functools.partial(run_job, context, handlers=handling(endless)))
    await runner.enqueue(job_id)
    await asyncio.wait_for(working.wait(), 5)
    await runner.stop()

    assert (await the_job(context.database, job_id)).status == JobStatus.RUNNING


# --- reading a job -----------------------------------------------------------------------------


@pytest.fixture
async def primer(session: AsyncSession) -> Office:
    return await office(session, "Primer Računovodstvo", "primer.example")


async def test_a_member_reads_the_job_they_started(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    job = await factories.job(session, primer.organization, primer.client, progress={"done": 3})

    response = await api.get(f"/jobs/{job.id}", headers=primer.as_client())

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json() == {
        "id": str(job.id),
        "kind": "revalidation",
        "status": "queued",
        "submitted_by": str(primer.client.id),
        "created_at": response.json()["created_at"],
        "started_at": None,
        "finished_at": None,
        "progress": {"done": 3},
        "result": None,
        "error": None,
        "version": 0,
    }


async def test_owners_and_accountants_read_every_job_and_a_client_only_their_own(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    accountants = await factories.job(session, primer.organization, primer.accountant)

    answers = {
        role: (await api.get(f"/jobs/{accountants.id}", headers=headers)).status_code
        for role, headers in [
            ("owner", primer.as_owner()),
            ("accountant", primer.as_accountant()),
            ("client", primer.as_client()),
        ]
    }

    assert answers == {"owner": 200, "accountant": 200, "client": 404}


async def test_an_unknown_job_is_not_found(api: AsyncClient, primer: Office) -> None:
    response = await api.get(f"/jobs/{uuid.uuid4()}", headers=primer.as_owner())

    assert (response.status_code, response.json()) == (
        404,
        {"detail": "no such job in this organization"},
    )


# --- following a job ---------------------------------------------------------------------------


@pytest.fixture
async def following(
    database_url: str, committed_database: Database, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[FastAPI]:
    """An application on the suite's database whose streams read their job every 10 ms."""
    monkeypatch.setattr(routes, "POLL_SECONDS", 0.01)
    app = create_app(settings_for(database_url))
    yield app
    await app.state.database.engine.dispose()


async def rest_of(stream: EventStream) -> list[dict[str, str]]:
    """The events until the stream ends."""
    events = []
    while (event := await stream.next_event()) is not None:
        events.append(event)
    return events


def job_in(event: dict[str, str] | None) -> dict[str, Any]:
    assert event is not None
    assert event["event"] == "job"
    job: dict[str, Any] = json.loads(event["data"])
    assert job["version"] == int(event["id"])
    return job


async def test_a_member_follows_a_job_from_its_start_to_its_end(
    following: FastAPI, context: JobContext
) -> None:
    job_id, owner = await owned_job(context.database)
    steps = [asyncio.Event(), asyncio.Event()]

    async def stepping(_context: JobContext, _job: Claimed, progress: Progress) -> dict[str, Any]:
        for done, step in enumerate(steps, start=1):
            await step.wait()
            await progress.report({"done": done})
        return {"done": 2}

    async with EventStream(following, f"/jobs/{job_id}/events", owner) as stream:
        waiting = job_in(await stream.next_event())
        running = asyncio.create_task(run_job(context, job_id, handling(stepping)))
        taken_on = job_in(await stream.next_event())
        steps[0].set()
        halfway = job_in(await stream.next_event())
        steps[1].set()
        await running
        rest = [job_in(event) for event in await rest_of(stream)]

    assert (stream.status, stream.headers["content-type"]) == (
        200,
        "text/event-stream; charset=utf-8",
    )
    assert (stream.headers["cache-control"], stream.headers["x-accel-buffering"]) == (
        "no-cache, no-store",
        "no",
    )
    assert [(job["version"], job["status"]) for job in (waiting, taken_on, halfway)] == [
        (0, "queued"),
        (1, "running"),
        (2, "running"),
    ]
    assert halfway["progress"] == {"done": 1}
    assert [job["version"] for job in rest] in ([3, 4], [4])
    assert (rest[-1]["status"], rest[-1]["result"]) == ("succeeded", {"done": 2})


async def test_a_client_that_reconnects_is_sent_only_what_changed_after_its_last_event(
    following: FastAPI, context: JobContext
) -> None:
    job_id, owner = await owned_job(context.database)
    await run_job(context, job_id, handling(counting_to_two))  # finished at version 4
    path = f"/jobs/{job_id}/events"

    async with EventStream(following, path, owner | {"Last-Event-ID": "3"}) as behind:
        caught_up = [job_in(event)["version"] for event in await rest_of(behind)]
    async with EventStream(following, path, owner | {"Last-Event-ID": "4"}) as current:
        nothing = await rest_of(current)

    assert (caught_up, nothing) == ([4], [])


async def test_a_stream_holds_no_connection_while_it_waits_and_ends_when_its_client_goes(
    following: FastAPI, context: JobContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stream would read the job again in ten seconds; the client leaves before."""
    monkeypatch.setattr(routes, "POLL_SECONDS", 10.0)
    job_id, owner = await owned_job(context.database)

    async with EventStream(following, f"/jobs/{job_id}/events", owner) as stream:
        job_in(await stream.next_event())
        connections = following.state.database.engine.pool.checkedout()

    assert connections == 0


async def test_a_stream_ends_after_its_time_even_while_the_job_goes_on(
    following: FastAPI, context: JobContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(routes, "STREAM_SECONDS", 0.0)
    job_id, owner = await owned_job(context.database)

    async with EventStream(following, f"/jobs/{job_id}/events", owner) as stream:
        events = await rest_of(stream)

    assert [job_in(event)["status"] for event in events] == ["queued"]


async def test_a_stream_ends_when_its_job_is_gone(following: FastAPI, context: JobContext) -> None:
    job_id, owner = await owned_job(context.database)

    async with EventStream(following, f"/jobs/{job_id}/events", owner) as stream:
        job_in(await stream.next_event())
        async with context.database.sessions() as session:
            await session.execute(delete(Organization))
            await session.commit()
        rest = await rest_of(stream)

    assert rest == []


async def test_a_job_the_caller_may_not_see_cannot_be_followed(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    """The answer comes before any stream, as JSON."""
    accountants = await factories.job(session, primer.organization, primer.accountant)
    path = f"/jobs/{accountants.id}/events"

    hidden = await api.get(path, headers=primer.as_client())
    garbled = await api.get(path, headers=primer.as_owner() | {"Last-Event-ID": "seven"})

    assert (hidden.status_code, hidden.json()) == (
        404,
        {"detail": "no such job in this organization"},
    )
    assert (garbled.status_code, garbled.headers["content-type"]) == (
        422,
        "application/json; charset=utf-8",
    )
