"""What is deleted after its retention period: finished jobs, never one under way (ADR-0038),
and the invoices an organization keeps past the period it set, never another's (ADR-0039)."""

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
from sef_api.jobs import worker
from sef_api.jobs.runs import JobContext
from sef_api.main import create_app
from sef_api.models import AuditAction, AuditEvent, Job, JobStatus, Role, StoredInvoice
from sef_api.settings import Settings

from . import factories
from .conftest import UNREACHABLE_DATABASE, settings_for
from .test_invoices_validate import Scripted

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


async def invoices_of_every_age(database: Database, now: datetime = NOW) -> dict[str, uuid.UUID]:
    """Invoices stored 10, 40 and 400 days before ``now`` by an organization that keeps them 30
    days, by one that keeps them a year, and by one that set no period; committed."""
    async with database.sessions() as session:
        vesna = await factories.person(session, "vesna@primer.example")
        invoices: dict[str, StoredInvoice] = {}
        for name, period in (("30 days", 30), ("a year", 365), ("no period", None)):
            organization = await factories.organization(session, f"Keeps {name}")
            organization.invoice_retention_days = period
            for days in (10, 40, 400):
                invoices[f"{name}: stored {days} days ago"] = await factories.stored_invoice(
                    session,
                    organization,
                    vesna,
                    f"<Invoice>{name} {days}</Invoice>".encode(),
                    created_at=now - timedelta(days=days),
                )
        await session.commit()
        return {name: invoice.id for name, invoice in invoices.items()}


async def invoices_kept(database: Database, invoices: dict[str, uuid.UUID]) -> set[str]:
    async with database.sessions() as session:
        remaining = set(await session.scalars(select(StoredInvoice.id)))
    return {name for name, invoice_id in invoices.items() if invoice_id in remaining}


async def test_invoices_stored_longer_ago_than_their_organizations_period_are_deleted(
    committed_database: Database,
) -> None:
    invoices = await invoices_of_every_age(committed_database)

    forgotten = await retention.forget_old_invoices(committed_database, now=NOW)

    assert forgotten == 3
    assert await invoices_kept(committed_database, invoices) == {
        "30 days: stored 10 days ago",
        "a year: stored 10 days ago",
        "a year: stored 40 days ago",
        "no period: stored 10 days ago",
        "no period: stored 40 days ago",
        "no period: stored 400 days ago",
    }


async def test_the_audit_log_keeps_what_it_named_of_a_deleted_invoice(
    committed_database: Database,
) -> None:
    invoices = await invoices_of_every_age(committed_database)
    deleted = invoices["30 days: stored 40 days ago"]
    async with committed_database.sessions() as session:
        invoice = await session.get(StoredInvoice, deleted)
        assert invoice is not None
        session.add(
            AuditEvent(
                organization_id=invoice.organization_id,
                actor=uuid.uuid4(),
                action=AuditAction.REPAIR_PROPOSED,
                invoice_id=deleted,
                repair_id=uuid.uuid4(),
            )
        )
        await session.commit()

    await retention.forget_old_invoices(committed_database, now=NOW)

    async with committed_database.sessions() as session:
        named = await session.scalars(select(AuditEvent.invoice_id))
        assert list(named) == [deleted]


async def test_the_api_deletes_them_when_it_starts(
    database_url: str, committed_database: Database
) -> None:
    # No job under way, which the start would run again.
    now = datetime.now(UTC)
    jobs = await jobs_of_every_age(committed_database, now, under_way=False)
    invoices = await invoices_of_every_age(committed_database, now)
    app = create_app(settings_for(database_url))

    async with app.router.lifespan_context(app):
        for _ in range(100):
            done = await kept(committed_database, jobs) != set(jobs)
            if done and await invoices_kept(committed_database, invoices) != set(invoices):
                break
            await asyncio.sleep(0.05)

    assert await kept(committed_database, jobs) == {"succeeded 29 days ago"}
    assert len(await invoices_kept(committed_database, invoices)) == 6


async def test_a_workers_deletion_deletes_them(committed_database: Database) -> None:
    now = datetime.now(UTC)
    jobs = await jobs_of_every_age(committed_database, now)
    invoices = await invoices_of_every_age(committed_database, now)
    context = JobContext(committed_database, Scripted(), settings_for())

    await worker.forget({"context": context})

    assert await kept(committed_database, jobs) == {
        "succeeded 29 days ago",
        "running for 40 days",
        "queued 40 days ago",
    }
    assert len(await invoices_kept(committed_database, invoices)) == 6


async def test_a_deletion_that_fails_is_logged_by_its_kind_and_tried_again(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(retention, "FORGET_EVERY_SECONDS", 0.01)
    database = Database.connect(UNREACHABLE_DATABASE, pooled=False)
    caplog.set_level(logging.WARNING, logger=retention.__name__)

    forgetting = asyncio.create_task(retention.keep_forgetting(database, 30))
    for _ in range(200):
        if len(caplog.records) >= 4:
            break
        await asyncio.sleep(0.05)
    forgetting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await forgetting
    await database.engine.dispose()

    messages = [record.getMessage() for record in caplog.records]
    # each deletion tried, and tried again, though the other failed
    assert len(messages) >= 4
    assert messages[0].startswith("the old finished jobs were not deleted: ")
    assert messages[1].startswith("the invoices past their retention were not deleted: ")
    for message in messages:
        # the kind of the error alone: no address, no message of the driver
        assert re.fullmatch(
            r"the (old finished jobs|invoices past their retention) were not deleted: \w+",
            message,
        )


def test_the_period_is_thirty_days_unless_set_and_at_least_one() -> None:
    assert settings_for().job_retention_days == 30
    assert settings_for(SEF_JOB_RETENTION_DAYS="7").job_retention_days == 7
    with pytest.raises(ValidationError, match="SEF_JOB_RETENTION_DAYS"):
        Settings.from_values({"SEF_ENVIRONMENT": "test", "SEF_JOB_RETENTION_DAYS": "0"})
