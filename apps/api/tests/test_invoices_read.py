"""Reading stored invoices: a page at a time and newest first, one with its report, its
document byte for byte, and only among those the caller may see."""

from __future__ import annotations

import base64
import re
from datetime import UTC, date, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.invoices import store
from sef_api.invoices.store import cursor_after

from .factories import Office, office, stored_invoice
from .test_invoices_validate import VALID, XML

NOT_FOUND = {"detail": "no such invoice in this organization"}
#: A cursor as this API makes them, but with a time without its zone.
NAIVE = base64.urlsafe_b64encode(
    b"2026-11-04T09:00:00 " + b"0" * 8 + b"-0000-4000-8000-" + b"0" * 12
)


@pytest.fixture
async def primer(session: AsyncSession) -> Office:
    return await office(session, "Primer Računovodstvo", "primer.example")


def at(minute: int) -> datetime:
    return datetime(2026, 11, 4, 9, minute, tzinfo=UTC)


async def listed(api: AsyncClient, member: dict[str, str], **params: Any) -> Any:
    response = await api.get("/invoices", params=params, headers=member)
    assert response.status_code == 200, response.text
    return response.json()


def ids(page: Any) -> list[str]:
    return [invoice["id"] for invoice in page["invoices"]]


async def test_invoices_are_listed_newest_first_a_page_at_a_time(
    api: AsyncClient, primer: Office, session: AsyncSession
) -> None:
    stored = [
        await stored_invoice(session, primer.organization, primer.client, created_at=at(n))
        for n in range(5)
    ]

    first = await listed(api, primer.as_owner(), limit=2)
    second = await listed(api, primer.as_owner(), limit=2, after=first["next"])
    third = await listed(api, primer.as_owner(), limit=2, after=second["next"])

    newest_first = [str(invoice.id) for invoice in reversed(stored)]
    assert [ids(first), ids(second), ids(third)] == [
        newest_first[:2],
        newest_first[2:4],
        newest_first[4:],
    ]
    assert third["next"] is None
    assert [page["total"] for page in (first, second, third)] == [5, 5, 5]


async def test_invoices_stored_at_the_same_moment_are_each_listed_once(
    api: AsyncClient, primer: Office, session: AsyncSession
) -> None:
    """The cursor names the time and the id: a page that ends inside a tie continues it."""
    stored = {
        str((await stored_invoice(session, primer.organization, None, created_at=at(0))).id)
        for _ in range(3)
    }
    seen: list[str] = []
    after: dict[str, str] = {}

    while True:
        page = await listed(api, primer.as_owner(), limit=1, **after)
        seen += ids(page)
        if page["next"] is None:
            break
        after = {"after": page["next"]}

    assert sorted(seen) == sorted(stored)


async def test_invoices_are_listed_by_the_verdict_of_their_latest_report(
    api: AsyncClient, primer: Office, session: AsyncSession
) -> None:
    """The invalid ones, a page at a time: what a revalidation left to fix."""
    stored = [
        await stored_invoice(
            session, primer.organization, primer.client, created_at=at(n), valid=verdict
        )
        for n, verdict in enumerate([True, False, True, False, False])
    ]
    newest_first = list(reversed(stored))

    first = await listed(api, primer.as_owner(), valid="false", limit=2)
    second = await listed(api, primer.as_owner(), valid="false", limit=2, after=first["next"])
    valid = await listed(api, primer.as_owner(), valid="true")
    every = await listed(api, primer.as_owner())

    assert ids(first) + ids(second) == [str(each.id) for each in newest_first if not each.valid]
    assert second["next"] is None
    assert [invoice["valid"] for invoice in first["invoices"] + second["invoices"]] == [False] * 3
    assert ids(valid) == [str(each.id) for each in newest_first if each.valid]
    assert ids(every) == [str(each.id) for each in newest_first]


async def test_a_client_lists_by_verdict_only_the_invoices_they_submitted(
    api: AsyncClient, primer: Office, session: AsyncSession
) -> None:
    own = await stored_invoice(session, primer.organization, primer.client, created_at=at(1))
    await stored_invoice(session, primer.organization, primer.accountant, created_at=at(2))
    await stored_invoice(session, primer.organization, primer.client, created_at=at(3), valid=True)

    assert ids(await listed(api, primer.as_client(), valid="false")) == [str(own.id)]


async def test_the_invalid_invoices_are_read_through_an_index_of_their_own(
    primer: Office, session: AsyncSession
) -> None:
    """The planner may use a partial index only for a query whose predicate implies the
    index's, ``NOT valid``. The listing's statement says ``valid = false`` in its text, not as
    a parameter, so that a generic plan of the prepared statement may use it too. With the
    other index of the listing dropped (inside the test's transaction, which is rolled back)
    and sequential scans off, the plan reads the partial index exactly when it may."""
    for minute in range(40):
        await stored_invoice(
            session, primer.organization, None, created_at=at(minute), valid=minute % 10 != 0
        )
    connection = await session.connection()
    await connection.exec_driver_sql("DROP INDEX ix_invoices_organization_id_created_at_id")
    statements: list[tuple[str, Any]] = []

    def capture(*arguments: Any) -> None:
        _, _, statement, parameters, *_ = arguments
        statements.append((statement, parameters))

    event.listen(connection.sync_connection, "before_cursor_execute", capture)
    try:
        page = await store.page_of(
            session, store.Scope(primer.organization.id), limit=10, valid=False
        )
    finally:
        event.remove(connection.sync_connection, "before_cursor_execute", capture)
    ((statement, parameters),) = statements
    await connection.exec_driver_sql("SET LOCAL enable_seqscan = off")
    plan = await connection.exec_driver_sql(f"EXPLAIN {statement}", parameters)

    assert len(page.invoices) == 4
    assert "invoices.valid = false" in statement
    assert "ix_invoices_invalid_organization_id_created_at_id" in "\n".join(plan.scalars())


async def test_a_verdict_is_true_or_false(api: AsyncClient, primer: Office) -> None:
    response = await api.get("/invoices", params={"valid": "maybe"}, headers=primer.as_owner())

    assert response.status_code == 422


async def test_a_list_says_what_the_validator_read_without_the_reports(
    api: AsyncClient, primer: Office
) -> None:
    stored = await api.post("/invoices", content=VALID, headers=XML | primer.as_client())

    page = await listed(api, primer.as_client())

    assert page == {
        "invoices": [{key: value for key, value in stored.json().items() if key != "report"}],
        "next": None,
        "total": 1,
    }


@pytest.mark.parametrize(
    "after",
    [
        "not-a-cursor",
        "bm90IGEgY3Vyc29y",  # base64 of "not a cursor"
        NAIVE.decode().rstrip("="),
    ],
    ids=["text", "base64", "no-time-zone"],
)
async def test_a_page_continues_only_from_a_cursor_this_api_gave(
    api: AsyncClient, primer: Office, after: str
) -> None:
    response = await api.get("/invoices", params={"after": after}, headers=primer.as_owner())

    assert (response.status_code, response.json()) == (
        422,
        {"detail": "after is not a cursor this API gave"},
    )


@pytest.mark.parametrize("limit", ["0", "101"])
async def test_a_page_lists_1_to_100_invoices(api: AsyncClient, primer: Office, limit: str) -> None:
    response = await api.get("/invoices", params={"limit": limit}, headers=primer.as_owner())

    assert response.status_code == 422


async def test_a_cursor_is_safe_in_a_url(primer: Office, session: AsyncSession) -> None:
    invoice = await stored_invoice(session, primer.organization, None, created_at=at(1))

    assert re.fullmatch(r"[A-Za-z0-9_-]+", cursor_after(invoice))


async def test_an_invoice_is_read_as_it_was_stored(api: AsyncClient, primer: Office) -> None:
    stored = await api.post("/invoices", content=VALID, headers=XML | primer.as_client())

    read = await api.get(stored.headers["Location"], headers=primer.as_client())

    assert read.status_code == 200
    assert read.json() == stored.json()
    assert read.headers["Cache-Control"] == "no-store"


async def test_a_document_is_downloaded_byte_for_byte_as_an_attachment(
    api: AsyncClient, primer: Office, session: AsyncSession
) -> None:
    """Saved, never rendered: a hostile document could carry markup a browser would run."""
    document = b"\xef\xbb\xbf<?xml version='1.0'?>\r\n<Invoice/>\r\n"
    invoice = await stored_invoice(session, primer.organization, primer.client, document)

    response = await api.get(f"/invoices/{invoice.id}/content", headers=primer.as_client())

    assert response.status_code == 200
    assert response.content == document
    assert response.headers["Content-Type"] == "application/xml"
    assert response.headers["Content-Disposition"] == (
        f'attachment; filename="invoice-{invoice.id}.xml"'
    )
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Cache-Control"] == "no-store"


async def test_a_client_sees_only_the_invoices_they_submitted(
    api: AsyncClient, primer: Office, session: AsyncSession
) -> None:
    """Within the organization too: an accounting office's clients do not see each other's
    invoices. The owner and the accountant see them all."""
    own = await stored_invoice(session, primer.organization, primer.client, created_at=at(1))
    other = await stored_invoice(session, primer.organization, primer.accountant, created_at=at(2))

    assert ids(await listed(api, primer.as_client())) == [str(own.id)]
    for path in (f"/invoices/{other.id}", f"/invoices/{other.id}/content"):
        response = await api.get(path, headers=primer.as_client())
        assert (response.status_code, response.json()) == (404, NOT_FOUND)
    for manager in (primer.as_owner(), primer.as_accountant()):
        assert ids(await listed(api, manager)) == [str(other.id), str(own.id)]


async def test_an_invoice_that_does_not_exist_is_not_found(
    api: AsyncClient, primer: Office
) -> None:
    missing = "00000000-0000-4000-8000-000000000000"

    for path in (f"/invoices/{missing}", f"/invoices/{missing}/content"):
        response = await api.get(path, headers=primer.as_owner())
        assert (response.status_code, response.json()) == (404, NOT_FOUND)


@pytest.fixture
async def searchable(session: AsyncSession, primer: Office) -> dict[str, str]:
    other = await office(session, "Druga kancelarija", "druga.example")
    ids_by_number = {}
    for minute, (number, seller, buyer, day, kind, valid, member) in enumerate(
        [
            ("F-%_!01", "ЕПС Оглед", "Radionica", 1, "Invoice", False, primer.client),
            ("F-XA!01", "Park", "RADIONICA", 2, "CreditNote", True, primer.client),
            ("F-003", "Park", "Radionica", 3, "Invoice", True, primer.accountant),
            ("F-004", None, None, None, "Invoice", False, primer.client),
        ]
    ):
        row = await stored_invoice(
            session,
            primer.organization,
            member,
            created_at=at(minute),
            number=number if day else None,
            seller=seller,
            buyer=buyer,
            document_type=kind if day else None,
            valid=valid,
            issue_date=date(2026, 11, day) if day else None,
            payable_amount=120 if day else None,
        )
        ids_by_number[number] = str(row.id)
    await stored_invoice(session, other.organization, other.owner, seller="ЕПС Оглед")
    return ids_by_number


@pytest.mark.parametrize(
    ("filters", "numbers"),
    [
        ({"q": "  f-003  "}, ["F-003"]),
        ({"q": "епс"}, ["F-%_!01"]),
        ({"q": "radionica"}, ["F-003", "F-XA!01", "F-%_!01"]),
        ({"q": "%"}, ["F-%_!01"]),
        ({"q": "_"}, ["F-%_!01"]),
        ({"q": "%_!"}, ["F-%_!01"]),
        ({"issued_from": "2026-11-02"}, ["F-003", "F-XA!01"]),
        ({"issued_to": "2026-11-02"}, ["F-XA!01", "F-%_!01"]),
        ({"document_type": "CreditNote"}, ["F-XA!01"]),
        (
            {
                "q": "radionica",
                "valid": "true",
                "issued_from": "2026-11-02",
                "issued_to": "2026-11-02",
                "document_type": "CreditNote",
            },
            ["F-XA!01"],
        ),
        ({"q": "missing"}, []),
    ],
)
async def test_invoice_list_filters(
    api: AsyncClient,
    primer: Office,
    searchable: dict[str, str],
    filters: dict[str, str],
    numbers: list[str],
) -> None:
    page = await listed(api, primer.as_owner(), **filters)

    assert ids(page) == [searchable[number] for number in numbers]
    assert page["total"] == len(numbers)


async def test_filtered_totals_span_pages_and_stay_inside_the_callers_scope(
    api: AsyncClient,
    primer: Office,
    searchable: dict[str, str],
) -> None:
    first = await listed(api, primer.as_client(), q="radionica", limit=1)
    second = await listed(api, primer.as_client(), q="radionica", limit=1, after=first["next"])
    assert (ids(first), ids(second)) == ([searchable["F-XA!01"]], [searchable["F-%_!01"]])
    assert first["total"] == second["total"] == 2
    assert second["next"] is None


@pytest.mark.parametrize(
    "filters",
    [
        {"q": ""},
        {"q": "   "},
        {"q": "a" * 101},
        {"issued_from": "yesterday"},
        {"issued_to": "2026-11-31"},
        {"issued_from": "2026-11-03", "issued_to": "2026-11-02"},
        {"document_type": "Other"},
    ],
)
async def test_invalid_list_filters_are_refused(
    api: AsyncClient,
    primer: Office,
    filters: dict[str, str],
) -> None:
    result = await api.get("/invoices", params=filters, headers=primer.as_owner())

    assert result.status_code == 422
