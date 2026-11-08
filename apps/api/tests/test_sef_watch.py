"""Where the invoices SEF imported stand, asked of SEF until each is final (ADR-0051): which are
due, how often, what is kept, what a failure leaves, and that two processes never ask about one
invoice at once. SEF answers through a mock transport; the rounds commit, on the suite's
database."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
import pytest
from sqlalchemy import select

from sef_api.db import Database
from sef_api.invoices.validator import Validator
from sef_api.jobs import worker
from sef_api.jobs.runs import JobContext
from sef_api.main import create_app
from sef_api.models import SefSubmission, SubmissionState
from sef_api.sef import watch
from sef_api.sef.keys import Keyring

from .conftest import settings_for
from .factories import KEYRING, office, sef_key, stored_invoice
from .test_sef_keys import NEXT_FERNET_KEY

NOW = datetime(2026, 11, 8, 21, 0, tzinfo=UTC)
SEF = "https://demoefaktura.mfin.gov.rs"


class FakeSef:
    """SEF's demo environment: each sales invoice's status, and who asked about which."""

    def __init__(self, answer: Callable[[int], httpx.Response] | None = None) -> None:
        self.asked: list[int] = []
        self.answer = answer or (lambda _: standing("Sent"))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        sales_invoice_id = int(request.url.params["invoiceId"])
        self.asked.append(sales_invoice_id)
        return self.answer(sales_invoice_id)


def standing(status: str, **body: Any) -> httpx.Response:
    return httpx.Response(
        200, json={"status": status, "lastModifiedUtc": "2026-11-08T20:59:00", **body}
    )


async def sent(
    database: Database, *imported: dict[str, Any], key: str = "4711-4711-4711-4711"
) -> list[SefSubmission]:
    """Primer's invoices sent to SEF, one an entry of ``imported``, whose keys are the
    submission's columns: imported an hour and a half ago and never asked about, unless they
    say otherwise."""
    async with database.sessions() as session:
        primer = await office(session, "Primer Računovodstvo", "primer.example")
        await sef_key(session, primer.organization, key)
        rows = []
        for number, columns in enumerate(imported, start=1):
            content = f"<Invoice>{number}</Invoice>".encode()
            invoice = await stored_invoice(session, primer.organization, primer.client, content)
            row = SefSubmission(
                organization_id=primer.organization.id,
                invoice_id=invoice.id,
                sha256=hashlib.sha256(content).hexdigest(),
                **(
                    {
                        "state": SubmissionState.IMPORTED,
                        "sales_invoice_id": 4700 + number,
                        "sent_at": NOW - timedelta(minutes=90),
                    }
                    | columns
                ),
            )
            session.add(row)
            rows.append(row)
        await session.commit()
        return rows


async def round_of(database: Database, fake: FakeSef, keyring: Keyring = KEYRING) -> int:
    async with httpx.AsyncClient(transport=httpx.MockTransport(fake)) as http:
        return await watch.watch_once(database, keyring, http, SEF, now=NOW)


async def kept(database: Database) -> dict[int | None, tuple[str | None, str | None]]:
    """Each sales invoice's status and detail, as kept."""
    async with database.sessions() as session:
        rows = await session.execute(
            select(SefSubmission.sales_invoice_id, SefSubmission.sef_status, SefSubmission.detail)
        )
        return {sales_id: (status, detail) for sales_id, status, detail in rows.all()}


# --- which invoices, and when -------------------------------------------------------------------


async def test_an_imported_invoice_is_asked_about_and_its_status_kept(
    committed_database: Database,
) -> None:
    await sent(committed_database, {})
    fake = FakeSef()

    answered = await round_of(committed_database, fake)

    assert (answered, fake.asked) == (1, [4701])
    assert await kept(committed_database) == {4701: ("Sent", None)}


async def test_only_the_invoices_imported_and_not_final_are_asked_about(
    committed_database: Database,
) -> None:
    await sent(
        committed_database,
        {},
        {"sef_status": "Approved"},
        {"sef_status": "Storno"},
        {"state": SubmissionState.UNCONFIRMED, "sales_invoice_id": None},
        {"state": SubmissionState.REFUSED, "sales_invoice_id": None, "refusal": "invoice"},
        {"sent_at": NOW - timedelta(days=31)},
    )
    fake = FakeSef()

    await round_of(committed_database, fake)

    assert fake.asked == [4701]


@pytest.mark.parametrize(
    ("sent_ago", "checked_ago", "due"),
    [
        (timedelta(minutes=10), timedelta(seconds=30), False),
        (timedelta(minutes=10), timedelta(minutes=1), True),
        (timedelta(hours=2), timedelta(minutes=10), False),
        (timedelta(hours=2), timedelta(minutes=15), True),
        (timedelta(days=3), timedelta(hours=5), False),
        (timedelta(days=3), timedelta(hours=6), True),
    ],
    ids=[
        "within the hour, asked half a minute ago",
        "within the hour, asked a minute ago",
        "on its first day, asked ten minutes ago",
        "on its first day, asked a quarter of an hour ago",
        "later, asked five hours ago",
        "later, asked six hours ago",
    ],
)
async def test_an_invoice_is_asked_about_less_often_as_it_ages(
    committed_database: Database, sent_ago: timedelta, checked_ago: timedelta, due: bool
) -> None:
    await sent(committed_database, {"sent_at": NOW - sent_ago, "checked_at": NOW - checked_ago})
    fake = FakeSef()

    await round_of(committed_database, fake)

    assert fake.asked == ([4701] if due else [])


async def test_a_round_asks_about_twenty_invoices_at_most(
    committed_database: Database,
) -> None:
    await sent(committed_database, *({} for _ in range(watch.BATCH + 5)))
    fake = FakeSef()

    first = await round_of(committed_database, fake)
    second = await round_of(committed_database, fake)

    assert (first, second) == (watch.BATCH, 5)
    assert sorted(fake.asked) == list(range(4701, 4701 + watch.BATCH + 5))


async def test_two_rounds_at_once_never_ask_about_one_invoice_twice(
    committed_database: Database,
) -> None:
    await sent(committed_database, *({} for _ in range(10)))
    fake = FakeSef()

    answered = await asyncio.gather(*(round_of(committed_database, fake) for _ in range(3)))

    assert sum(answered) == 10
    assert sorted(fake.asked) == list(range(4701, 4711))


# --- what SEF says -----------------------------------------------------------------------------


async def test_a_buyers_decision_is_kept_with_its_comment_and_asked_about_no_more(
    committed_database: Database,
) -> None:
    await sent(committed_database, {})
    fake = FakeSef(lambda _: standing("Rejected", comment="Pogrešan iznos"))

    await round_of(committed_database, fake)
    async with committed_database.sessions() as session:
        row = await session.scalar(select(SefSubmission))
        assert row is not None
        row.checked_at = NOW - timedelta(days=1)
        await session.commit()
    await round_of(committed_database, fake)

    assert await kept(committed_database) == {4701: ("Rejected", "Pogrešan iznos")}
    assert fake.asked == [4701]


async def test_sef_failing_leaves_the_status_and_waits_for_the_next_time(
    committed_database: Database, caplog: pytest.LogCaptureFixture
) -> None:
    await sent(committed_database, {"sef_status": "Sent"})
    fake = FakeSef(lambda _: httpx.Response(400, text="Faktura RF-2026-000123 ne postoji"))

    with caplog.at_level(logging.WARNING, logger="sef_api.sef.watch"):
        answered = await round_of(committed_database, fake)
        again = await round_of(committed_database, fake)

    assert (answered, again) == (0, 0)
    assert fake.asked == [4701]  # marked asked: not again within the minute
    assert await kept(committed_database) == {4701: ("Sent", None)}
    assert "SEF was not asked where an invoice stands: SEF: refused (400)" in caplog.text
    assert "RF-2026-000123" not in caplog.text


async def test_a_key_that_does_not_open_asks_nothing_and_says_so(
    committed_database: Database, caplog: pytest.LogCaptureFixture
) -> None:
    await sent(committed_database, {})
    fake = FakeSef()

    with caplog.at_level(logging.WARNING, logger="sef_api.sef.watch"):
        answered = await round_of(committed_database, fake, Keyring((NEXT_FERNET_KEY,)))

    assert (answered, fake.asked) == (0, [])
    assert "an organization's key to SEF cannot be opened with SEF_FERNET_KEY" in caplog.text
    assert "4711" not in caplog.text


# --- where it runs -----------------------------------------------------------------------------


async def test_without_a_keyring_nothing_is_watched(committed_database: Database) -> None:
    async with httpx.AsyncClient() as http:
        await asyncio.wait_for(watch.keep_watching(committed_database, None, http, SEF), 1)


async def test_a_worker_asks_with_its_own_keyring_and_connections(
    committed_database: Database, database_url: str
) -> None:
    await sent(committed_database, {"sent_at": datetime.now(UTC) - timedelta(minutes=5)})
    fake = FakeSef()
    ctx: dict[str, Any] = {
        "context": JobContext(
            committed_database, cast(Validator, None), settings_for(database_url)
        ),
        "sef_keys": KEYRING,
        "sef_http": httpx.AsyncClient(transport=httpx.MockTransport(fake)),
    }

    await worker.watch(ctx)
    await ctx["sef_http"].aclose()

    assert fake.asked == [4701]
    assert await kept(committed_database) == {4701: ("Sent", None)}


async def test_the_api_watches_where_its_jobs_run(
    committed_database: Database, database_url: str
) -> None:
    """With ``SEF_JOBS=inline``, the API's process asks, as soon as it starts."""
    await sent(committed_database, {"sent_at": datetime.now(UTC) - timedelta(minutes=5)})
    fake = FakeSef()
    app = create_app(settings_for(database_url))
    await app.state.sef_http.aclose()
    app.state.sef_http = httpx.AsyncClient(transport=httpx.MockTransport(fake))

    async with app.router.lifespan_context(app):
        for _ in range(200):
            if await kept(committed_database) == {4701: ("Sent", None)}:
                break
            await asyncio.sleep(0.05)

    assert fake.asked == [4701]
    assert await kept(committed_database) == {4701: ("Sent", None)}
