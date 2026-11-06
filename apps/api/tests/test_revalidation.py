"""``POST /invoices/revalidations``: stored invoices validated again in a job, within the
caller's scope and the organization's quota, one at a time, with progress from which an
attempt taken on again continues."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from einvoice_core.pipeline import ValidationReport
from einvoice_core.pipeline import validate as validate_with_the_core
from sef_api.auth.permissions import Permission
from sef_api.db import Database
from sef_api.invoices import revalidation, store
from sef_api.invoices.validation import Patched, Validation, outcome
from sef_api.invoices.validator import (
    TooManyElementsError,
    ValidationRefusedError,
    ValidationTimeoutError,
    ValidatorFailedError,
)
from sef_api.jobs.kinds import HANDLERS
from sef_api.jobs.runs import JobContext, run_job
from sef_api.main import create_app
from sef_api.models import Job, JobKind, StoredInvoice

from . import factories
from .conftest import settings_for
from .factories import Office, office
from .test_invoices_store import MIB, filler
from .test_invoices_validate import VALID, Scripted

#: What a revalidation that found nothing to do came to.
NOTHING = {"total": 0, "done": 0, "valid": 0, "invalid": 0, "kept": 0, "failed": 0, "deleted": 0}


class Judging:
    """A validator that judges every document ``valid`` or not and notes it; from the
    ``hold_from``-th document on, it holds each until it is let go."""

    problem = None

    def __init__(self, *, valid: bool = True, hold_from: int | None = None) -> None:
        self.valid = valid
        self.hold_from = hold_from
        self.seen: list[bytes] = []
        self.holding = asyncio.Event()
        self.release = asyncio.Event()

    async def start(self) -> None:
        pass

    async def validate(self, content: bytes, profile: str) -> Validation:
        self.seen.append(content)
        if self.hold_from is not None and len(self.seen) >= self.hold_from:
            self.holding.set()
            await self.release.wait()
        report = ValidationReport(profile=profile, valid=self.valid, violations=(), layers=())
        return Validation(report=report, summary=None)

    async def patch(
        self,
        _content: bytes,
        _profile: str,
        _patches: object,
        *,
        fields: bool = False,  # noqa: ARG002
    ) -> Patched:
        raise AssertionError("not patched in these tests")

    async def stop(self) -> None:
        pass


@dataclass(frozen=True)
class Offices:
    primer: Office
    ogled: Office


@pytest.fixture
async def offices(committed_database: Database) -> Offices:
    async with committed_database.sessions() as session:
        primer = await office(session, "Primer Računovodstvo", "primer.example")
        ogled = await office(session, "Ogled", "ogled.example")
        await session.commit()
    return Offices(primer, ogled)


@asynccontextmanager
async def application(
    database_url: str, validator: Any = None, **variables: str
) -> AsyncIterator[tuple[FastAPI, AsyncClient]]:
    """An application on the suite's database, as in production but for ``validator``, and a
    client of it. Its jobs run in its event loop: ``app.state.jobs.drain()`` waits for them."""
    app = create_app(settings_for(database_url, **variables))
    if validator is not None:
        app.state.validator = validator
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield app, client
    await app.state.jobs.stop()
    await app.state.database.engine.dispose()


async def stored(
    database: Database, office: Office, content: bytes = VALID, **columns: Any
) -> uuid.UUID:
    """An invoice the office's client submitted, with an empty report on it; committed."""
    async with database.sessions() as session:
        invoice = await factories.stored_invoice(
            session, office.organization, office.client, content, **columns
        )
        await session.commit()
        return invoice.id


async def invoice(database: Database, invoice_id: uuid.UUID) -> StoredInvoice:
    async with database.sessions() as session:
        found = await session.scalar(select(StoredInvoice).where(StoredInvoice.id == invoice_id))
        assert found is not None
        return found


async def job(database: Database, job_id: str) -> Job:
    async with database.sessions() as session:
        found = await session.scalar(select(Job).where(Job.id == uuid.UUID(job_id)))
        assert found is not None
        return found


def ids(*numbers: int) -> list[uuid.UUID]:
    """Invoice ids in the order a revalidation takes the invoices on."""
    return [uuid.UUID(int=number) for number in numbers]


async def test_stored_invoices_are_validated_again_and_keep_the_new_reports(
    committed_database: Database, database_url: str, offices: Offices
) -> None:
    primer = offices.primer
    valid = await stored(committed_database, primer, VALID)
    unreadable = await stored(committed_database, primer, b"<Invoice><cbc:ID>")
    before = await invoice(committed_database, valid)

    async with application(database_url) as (app, api):
        started = await api.post("/invoices/revalidations", headers=primer.as_owner())
        await app.state.jobs.drain()
        followed = await api.get(started.headers["Location"], headers=primer.as_owner())
        read = await api.get(f"/invoices/{valid}", headers=primer.as_owner())

    assert started.status_code == 202
    assert started.headers["Location"] == f"/jobs/{started.json()['id']}"
    assert started.headers["Cache-Control"] == "no-store"
    assert (started.json()["kind"], started.json()["status"]) == ("revalidation", "queued")
    assert started.json()["submitted_by"] == str(primer.owner.id)
    assert (followed.json()["status"], followed.json()["result"]) == (
        "succeeded",
        NOTHING | {"total": 2, "done": 2, "valid": 1, "invalid": 1},
    )
    after = await invoice(committed_database, valid)
    report = validate_with_the_core(VALID, "srb")
    assert (after.valid, after.report) == (True, report.model_dump(mode="json"))
    assert after.report_size == len(report.model_dump_json().encode())
    assert (before.number, after.number) == (None, "RF-2026-000124")
    assert after.payable_amount == Decimal("8400.00")
    assert after.created_at == before.created_at < after.validated_at
    assert read.json()["validated_at"] == after.validated_at.isoformat().replace("+00:00", "Z")
    assert read.json()["report"] == report.model_dump(mode="json")
    other = await invoice(committed_database, unreadable)
    assert [v["code"] for v in other.report["violations"]] == ["UNREADABLE"]


async def test_a_member_validates_again_only_the_invoices_they_may_see(
    committed_database: Database, database_url: str, offices: Offices
) -> None:
    """A client those they submitted; an accountant every one of the organization's, and none
    of another organization's."""
    primer = offices.primer
    clients = await stored(committed_database, primer)
    async with committed_database.sessions() as session:
        accountants = (
            await factories.stored_invoice(session, primer.organization, primer.accountant, VALID)
        ).id
        await session.commit()
    ogleds = await stored(committed_database, offices.ogled)

    async with application(database_url, Judging()) as (app, api):
        by_client = await api.post("/invoices/revalidations", headers=primer.as_client())
        await app.state.jobs.drain()
        after_client = [
            (await invoice(committed_database, i)).valid for i in (clients, accountants, ogleds)
        ]
        by_accountant = await api.post("/invoices/revalidations", headers=primer.as_accountant())
        await app.state.jobs.drain()
        after_accountant = [
            (await invoice(committed_database, i)).valid for i in (clients, accountants, ogleds)
        ]

    assert after_client == [True, False, False]
    assert after_accountant == [True, True, False]
    client_job = await job(committed_database, by_client.json()["id"])
    accountant_job = await job(committed_database, by_accountant.json()["id"])
    assert client_job.parameters == {"submitted_by": str(primer.client.id)}
    assert accountant_job.parameters == {}
    assert (client_job.result or {})["total"] == 1
    assert (accountant_job.result or {})["total"] == 2


async def test_an_invoice_stored_after_the_job_was_started_is_not_taken_on(
    committed_database: Database, database_url: str, offices: Offices
) -> None:
    """It was validated with the rules there are now when it was stored."""
    await stored(committed_database, offices.primer, created_at=func.now() + timedelta(days=1))
    judging = Judging()

    async with application(database_url, judging) as (app, api):
        started = await api.post("/invoices/revalidations", headers=offices.primer.as_owner())
        await app.state.jobs.drain()

    assert (await job(committed_database, started.json()["id"])).result == NOTHING
    assert judging.seen == []


async def test_an_api_key_validates_again_the_invoices_it_may_see(
    api: AsyncClient, session: AsyncSession
) -> None:
    """A key with ``invoices:manage`` the organization's invoices; one without, only its
    member's, even when the member may see them all."""
    primer = await office(session, "Primer Računovodstvo", "primer.example")
    narrow = await factories.api_key(
        session, primer.organization, primer.owner, Permission.INVOICES_SUBMIT
    )
    broad = await factories.api_key(session, primer.organization, primer.accountant)

    for key in (narrow, broad):
        assert (await api.post("/invoices/revalidations", headers=key.header())).status_code == 202

    started = (await session.execute(select(Job.submitted_by, Job.parameters))).all()
    assert sorted(started, key=lambda row: str(row[0])) == sorted(
        [
            (primer.owner.id, {"submitted_by": str(primer.owner.id)}),
            (primer.accountant.id, {}),
        ],
        key=lambda row: str(row[0]),
    )


async def test_an_invoice_whose_new_report_would_not_fit_the_quota_keeps_its_report(
    committed_database: Database, database_url: str, offices: Offices
) -> None:
    """Only a larger report is held to the quota: a smaller one replaces the old even in an
    organization that stores more than it may now, as after the quota was lowered."""
    primer = offices.primer
    growing, shrinking, filling = ids(1, 2, 3)
    await stored(committed_database, primer, id=growing)
    await stored(committed_database, primer, id=shrinking, report_size=50_000)
    async with committed_database.sessions() as session:
        stored_now = await store.stored_bytes(session, primer.organization.id)
        padding = filler(primer.organization, MIB + 100_000 - stored_now - 64)
        padding.id = filling
        session.add(padding)
        await session.commit()
    before = await invoice(committed_database, growing)

    async with application(database_url, SEF_MAX_STORED_BYTES=str(MIB)) as (app, api):
        started = await api.post("/invoices/revalidations", headers=primer.as_owner())
        await app.state.jobs.drain()

    assert (await job(committed_database, started.json()["id"])).result == NOTHING | {
        "total": 3,
        "done": 3,
        "valid": 1,
        "kept": 2,
    }
    kept = await invoice(committed_database, growing)
    assert (kept.report, kept.validated_at) == (before.report, before.validated_at)
    shrunk = await invoice(committed_database, shrinking)
    assert (shrunk.valid, shrunk.report_size < 50_000) == (True, True)
    async with committed_database.sessions() as session:
        stored_after = await store.stored_bytes(session, primer.organization.id)
    assert stored_after == MIB + 100_000 - 50_000 + shrunk.report_size


async def test_a_report_replaced_during_an_upload_cannot_take_an_organization_past_its_quota(
    committed_database: Database, offices: Offices, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both add up what is stored under the organization's lock: with room for one of them,
    one gets it, even when both add up before either writes."""
    primer = offices.primer
    invoice_id = await stored(committed_database, primer)
    _, detail = outcome(VALID, "srb", max_elements=20_000)
    validation = Validation.model_validate_json(detail)
    new = len(validation.report.model_dump_json().encode())
    old = (await invoice(committed_database, invoice_id)).report_size
    async with committed_database.sessions() as session:
        quota = await store.stored_bytes(session, primer.organization.id)
    quota += (new - old) + (len(VALID) + new) - 1
    real = store.stored_bytes

    async def slowly(session: AsyncSession, organization_id: Any) -> int:
        counted = await real(session, organization_id)
        await asyncio.sleep(0.2)  # the other adds up meanwhile, if nothing stops it
        return counted

    monkeypatch.setattr(store, "stored_bytes", slowly)

    async def replace() -> str:
        async with committed_database.sessions() as session:
            replaced = await store.replace_report(
                session,
                organization_id=primer.organization.id,
                invoice_id=invoice_id,
                validation=validation,
                quota=quota,
            )
            await session.commit()
            return replaced

    async def upload() -> str:
        async with committed_database.sessions() as session:
            try:
                await store.store(
                    session,
                    organization_id=primer.organization.id,
                    submitted_by=primer.client.id,
                    profile="srb",
                    content=VALID,
                    validation=validation,
                    quota=quota,
                )
            except store.StorageFullError:
                return "full"
            return "stored"

    results = set(await asyncio.gather(replace(), upload()))

    assert results in ({"replaced", "full"}, {"kept", "stored"})


@pytest.mark.parametrize(
    "error",
    [
        ValidationTimeoutError("the validation took longer than 10 seconds"),
        ValidationRefusedError("the rule sets could not be applied"),
        TooManyElementsError("the invoice has more than 20000 elements"),
        ValidatorFailedError("XMLSyntaxError"),
    ],
    ids=["timeout", "refused", "too-many-elements", "failed"],
)
async def test_an_invoice_that_cannot_be_validated_is_counted_and_keeps_its_report(
    committed_database: Database, database_url: str, offices: Offices, error: Exception
) -> None:
    invoice_id = await stored(committed_database, offices.primer)
    before = await invoice(committed_database, invoice_id)

    async with application(database_url, Scripted(error=error)) as (app, api):
        started = await api.post("/invoices/revalidations", headers=offices.primer.as_owner())
        await app.state.jobs.drain()

    finished = await job(committed_database, started.json()["id"])
    assert (finished.status, finished.result) == (
        "succeeded",
        NOTHING | {"total": 1, "done": 1, "failed": 1},
    )
    after = await invoice(committed_database, invoice_id)
    assert (after.report, after.validated_at) == (before.report, before.validated_at)


async def test_without_a_validator_the_job_fails_and_says_why(
    committed_database: Database, database_url: str, offices: Offices
) -> None:
    invoice_id = await stored(committed_database, offices.primer)
    unavailable = Scripted(problem="rule set 'ubl-2.1' is absent")

    async with application(database_url, unavailable) as (app, api):
        started = await api.post("/invoices/revalidations", headers=offices.primer.as_owner())
        await app.state.jobs.drain()

    failed = await job(committed_database, started.json()["id"])
    assert (failed.status, failed.error) == ("failed", revalidation.UNAVAILABLE)
    assert failed.progress == NOTHING | {"total": 1, "last": None}
    assert (await invoice(committed_database, invoice_id)).valid is False


async def test_invoices_deleted_while_the_job_runs_are_counted_as_deleted(
    committed_database: Database,
    database_url: str,
    offices: Offices,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deleted while it was validated, after it was looked up, or before the job reached it."""
    monkeypatch.setattr(revalidation, "PAGE", 2)
    validating, looked_up, kept, never_reached = ids(1, 2, 3, 4)
    for invoice_id in (validating, looked_up, kept, never_reached):
        await stored(committed_database, offices.primer, id=invoice_id)
    judging = Judging(hold_from=1)

    async with application(database_url, judging) as (app, api):
        started = await api.post("/invoices/revalidations", headers=offices.primer.as_owner())
        await asyncio.wait_for(judging.holding.wait(), 5)
        for gone in (validating, looked_up, never_reached):
            deleted = await api.delete(f"/invoices/{gone}", headers=offices.primer.as_owner())
            assert deleted.status_code == 204
        judging.release.set()
        await app.state.jobs.drain()

    assert (await job(committed_database, started.json()["id"])).result == NOTHING | {
        "total": 4,
        "done": 4,
        "valid": 1,
        "deleted": 3,
    }
    assert len(judging.seen) == 2
    assert (await invoice(committed_database, kept)).valid is True


async def test_a_member_follows_the_job_and_has_one_under_way_at_a_time(
    committed_database: Database, database_url: str, offices: Offices
) -> None:
    primer = offices.primer
    await stored(committed_database, primer)
    judging = Judging(hold_from=1)

    async with application(database_url, judging) as (app, api):
        first = await api.post("/invoices/revalidations", headers=primer.as_owner())
        await asyncio.wait_for(judging.holding.wait(), 5)
        running = await api.get(first.headers["Location"], headers=primer.as_owner())
        again = await api.post("/invoices/revalidations", headers=primer.as_owner())
        accountants = await api.post("/invoices/revalidations", headers=primer.as_accountant())
        judging.release.set()
        await app.state.jobs.drain()
        after = await api.post("/invoices/revalidations", headers=primer.as_owner())
        await app.state.jobs.drain()

    assert running.json()["status"] == "running"
    assert running.json()["progress"] == NOTHING | {"total": 1, "last": None}
    assert (again.status_code, again.json()) == (
        409,
        {"detail": "a revalidation you started is under way"},
    )
    assert again.headers["Location"] == first.headers["Location"]
    assert (accountants.status_code, after.status_code) == (202, 202)
    assert after.headers["Location"] != first.headers["Location"]


async def test_a_job_cut_short_when_the_api_stops_continues_when_it_starts_again(
    committed_database: Database, database_url: str, offices: Offices
) -> None:
    """From the invoice after the last one it did, with its counts: none is done twice."""
    primer = offices.primer
    for number, invoice_id in enumerate(ids(1, 2, 3), start=1):
        await stored(
            committed_database, primer, f"<Invoice>{number}</Invoice>".encode(), id=invoice_id
        )
    stopping = Judging(hold_from=2)

    async with application(database_url, stopping) as (app, api):
        async with app.router.lifespan_context(app):
            started = await api.post("/invoices/revalidations", headers=primer.as_owner())
            await asyncio.wait_for(stopping.holding.wait(), 5)
        stopping.release.set()  # an attempt the stop missed would go on now
        await app.state.jobs.drain()
    cut_short = await job(committed_database, started.json()["id"])
    starting = Judging()
    async with application(database_url, starting) as (app, _), app.router.lifespan_context(app):
        await app.state.jobs.drain()

    assert (cut_short.status, cut_short.progress["done"]) == ("running", 1)
    finished = await job(committed_database, started.json()["id"])
    assert (finished.status, finished.attempts) == ("succeeded", 2)
    assert finished.result == NOTHING | {"total": 3, "done": 3, "valid": 3}
    assert starting.seen == [b"<Invoice>2</Invoice>", b"<Invoice>3</Invoice>"]


async def test_an_attempt_that_was_superseded_replaces_no_report(
    committed_database: Database, database_url: str, offices: Offices
) -> None:
    """The first attempt judges the invoice invalid but is given up for dead while it does; the
    second judges it valid and finishes the job. The first's verdict is not written."""
    invoice_id = await stored(committed_database, offices.primer)
    first = Judging(valid=False, hold_from=1)

    async with application(database_url, first) as (app, api):
        started = await api.post("/invoices/revalidations", headers=offices.primer.as_owner())
        await asyncio.wait_for(first.holding.wait(), 5)
        second = JobContext(committed_database, Judging(), app.state.settings)
        await run_job(second, uuid.UUID(started.json()["id"]), HANDLERS)
        first.release.set()
        await app.state.jobs.drain()

    finished = await job(committed_database, started.json()["id"])
    assert (finished.status, finished.attempts) == ("succeeded", 2)
    assert finished.result == NOTHING | {"total": 1, "done": 1, "valid": 1}
    assert (await invoice(committed_database, invoice_id)).valid is True


async def test_without_its_database_the_api_starts_and_leaves_the_jobs_for_later(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_app(settings_for())
    app.state.validator = Judging()

    with caplog.at_level(logging.WARNING, logger="sef_api.main"):
        async with app.router.lifespan_context(app):
            pass

    assert "the unfinished jobs were not resumed" in caplog.text
    await app.state.database.engine.dispose()


def test_every_kind_of_job_has_a_handler() -> None:
    assert set(HANDLERS) == set(JobKind)
