"""An organization's credits, where billing is on (ADR-0059): one spent for each invoice it stores,
from the routes and from MCP; none below zero, even when two invoices are stored at once; a
ledger whose entries add up to the balance; the operator's grants. Billing is off by default, and
then storing costs nothing."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.billing import grant, ledger
from sef_api.db import Database
from sef_api.models import CreditAccount, CreditEntry, Organization, StoredInvoice

from .factories import Office, api_key, office
from .test_invoices_validate import VALID, XML, application
from .test_mcp import connected, serving, text_of

NO_CREDITS = "the organization has no credit left to store an invoice: the operator grants more"


@pytest.fixture
async def primer(session: AsyncSession) -> Office:
    return await office(session, "Primer Računovodstvo", "primer.example")


@asynccontextmanager
async def billing(session: AsyncSession, starting: int = 2) -> AsyncIterator[AsyncClient]:
    """A client of an application where billing is on, each organization starting with
    ``starting`` credits."""
    async with application(
        session, SEF_BILLING="credits", SEF_STARTING_CREDITS=str(starting)
    ) as api:
        yield api


async def store(api: AsyncClient, headers: dict[str, str]) -> Any:
    return await api.post("/invoices", content=VALID, headers=XML | headers)


async def stored(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(StoredInvoice)) or 0


async def ledger_sum(session: AsyncSession, organization: Organization) -> int:
    return (
        await session.scalar(
            select(func.coalesce(func.sum(CreditEntry.delta), 0)).where(
                CreditEntry.organization_id == organization.id
            )
        )
        or 0
    )


# --- billing off -------------------------------------------------------------------------------


async def test_with_billing_off_storing_costs_nothing_and_the_server_says_so(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    for _ in range(3):
        assert (await store(api, primer.as_client())).status_code == 201

    shown = await api.get("/billing", headers=primer.as_client())
    listed = await api.get("/billing/entries", headers=primer.as_owner())

    assert shown.json() == {
        "enabled": False,
        "balance": None,
        "starting": None,
        "per_invoice": None,
        "packs": [],
    }
    assert listed.json() == []
    assert await session.scalar(select(func.count()).select_from(CreditAccount)) == 0


# --- spending ----------------------------------------------------------------------------------


async def test_each_stored_invoice_spends_a_credit_written_to_the_ledger(
    session: AsyncSession, primer: Office
) -> None:
    async with billing(session, starting=2) as api:
        before = await api.get("/billing", headers=primer.as_client())
        response = await store(api, primer.as_client())
        after = await api.get("/billing", headers=primer.as_client())
        listed = await api.get("/billing/entries", headers=primer.as_owner())

    assert before.json() == {
        "enabled": True,
        "balance": 2,
        "starting": 2,
        "per_invoice": 1,
        "packs": [],
    }
    # Nothing is written until the organization first spends.
    assert response.status_code == 201
    assert after.json()["balance"] == 1
    spent, opened = listed.json()
    assert (spent["kind"], spent["delta"], spent["invoice_id"]) == (
        "spend",
        -1,
        response.json()["id"],
    )
    assert (opened["kind"], opened["delta"], opened["invoice_id"]) == ("opening", 2, None)
    assert await ledger_sum(session, primer.organization) == 1


async def test_without_a_credit_nothing_is_stored_and_nothing_is_spent(
    session: AsyncSession, primer: Office
) -> None:
    async with billing(session, starting=2) as api:
        kept = [(await store(api, primer.as_client())).status_code for _ in range(2)]
        refused = await store(api, primer.as_accountant())
        shown = await api.get("/billing", headers=primer.as_client())
        listed = await api.get("/billing/entries", headers=primer.as_owner())

    assert kept == [201, 201]
    assert (refused.status_code, refused.json()) == (402, {"detail": NO_CREDITS})
    assert await stored(session) == 2
    assert shown.json()["balance"] == 0
    assert [entry["kind"] for entry in listed.json()] == ["spend", "spend", "opening"]
    assert await ledger_sum(session, primer.organization) == 0


async def test_an_organization_that_starts_with_none_stores_nothing(
    session: AsyncSession, primer: Office
) -> None:
    async with billing(session, starting=0) as api:
        refused = await store(api, primer.as_client())
        listed = await api.get("/billing/entries", headers=primer.as_owner())

    assert refused.status_code == 402
    assert await stored(session) == 0
    assert listed.json() == []


async def test_each_organization_spends_its_own_credits(
    session: AsyncSession, primer: Office
) -> None:
    ogled = await office(session, "Ogled", "ogled.example")
    async with billing(session, starting=2) as api:
        await store(api, primer.as_client())
        await store(api, primer.as_client())
        primers = await api.get("/billing", headers=primer.as_client())
        ogleds = await api.get("/billing", headers=ogled.as_client())
        listed = await api.get("/billing/entries", headers=ogled.as_owner())

    assert (primers.json()["balance"], ogleds.json()["balance"]) == (0, 2)
    assert listed.json() == []


async def test_a_key_that_may_store_sees_the_credits_and_only_the_owner_the_ledger(
    session: AsyncSession, primer: Office
) -> None:
    key = await api_key(session, primer.organization, primer.client)
    async with billing(session) as api:
        by_key = await api.get("/billing", headers=key.header())
        refused = [
            (await api.get("/billing/entries", headers=headers)).status_code
            for headers in (primer.as_accountant(), primer.as_client(), key.header())
        ]

    assert by_key.json()["balance"] == 2
    assert refused == [403, 403, 403]


async def test_the_ledger_comes_in_pages_newest_first(
    session: AsyncSession, primer: Office
) -> None:
    async with billing(session, starting=5) as api:
        for _ in range(4):
            await store(api, primer.as_client())
        page = await api.get("/billing/entries", params={"limit": 2}, headers=primer.as_owner())
        too_many = await api.get(
            "/billing/entries", params={"limit": 101}, headers=primer.as_owner()
        )

    assert [entry["kind"] for entry in page.json()] == ["spend", "spend"]
    assert too_many.status_code == 422


async def test_two_spends_of_one_last_credit_spend_it_once(
    committed_database: Database,
) -> None:
    """The spend takes a credit only from an account that has one, in one statement: two at
    once, even outside the lock on the organization's storage, cannot go below zero."""
    async with committed_database.sessions() as setup:
        primer = Organization(name="Primer")
        setup.add(primer)
        await setup.commit()
    terms = ledger.CreditTerms(starting=1)

    async def spending() -> str:
        async with committed_database.sessions() as session:
            try:
                await ledger.spend(session, primer.id, terms, invoice_id=uuid.uuid4())
                await asyncio.sleep(0.2)  # the other spends meanwhile, if nothing stops it
                await session.commit()
            except ledger.NoCreditsError:
                return "refused"
            return "spent"

    results = await asyncio.gather(spending(), spending())

    assert sorted(results) == ["refused", "spent"]
    async with committed_database.sessions() as session:
        assert await ledger.balance(session, primer.id, terms) == 0
        assert await ledger_sum(session, primer) == 0


# --- MCP ---------------------------------------------------------------------------------------


async def test_an_mcp_client_spends_the_same_credits(
    committed_database: Database, database_url: str
) -> None:
    async with (
        serving(
            committed_database, database_url, SEF_BILLING="credits", SEF_STARTING_CREDITS="1"
        ) as served,
        connected(served.app, served.key) as client,
    ):
        kept = await client.call_tool("store_invoice", {"xml": VALID.decode()})
        refused = await client.call_tool("store_invoice", {"xml": VALID.decode()})

    assert not kept.is_error
    assert refused.is_error
    assert text_of(refused) == f"Error executing tool store_invoice: {NO_CREDITS}"


# --- the operator's grant ----------------------------------------------------------------------


async def test_the_operator_grants_credits_written_to_the_ledger(
    committed_database: Database,
) -> None:
    async with committed_database.sessions() as setup:
        primer = Organization(name="Primer")
        setup.add(primer)
        await setup.commit()
    terms = ledger.CreditTerms(starting=3)

    first = await grant.grant_credits(committed_database, terms, primer.id, 5)
    second = await grant.grant_credits(committed_database, terms, primer.id, 2)

    assert (first, second) == (8, 10)
    async with committed_database.sessions() as session:
        listed = await ledger.entries(session, primer.id)
        assert [(entry.kind, entry.delta) for entry in listed] == [
            ("grant", 2),
            ("grant", 5),
            ("opening", 3),
        ]
        assert await ledger_sum(session, primer) == 10


async def test_the_grant_command_says_what_it_did(
    committed_database: Database,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async with committed_database.sessions() as setup:
        primer = Organization(name="Primer")
        setup.add(primer)
        await setup.commit()
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("SEF_BILLING", "credits")
    monkeypatch.setenv("SEF_STARTING_CREDITS", "0")

    gave = await asyncio.to_thread(grant.main, [str(primer.id), "7"])
    nobody = await asyncio.to_thread(grant.main, [str(uuid.uuid4()), "7"])
    monkeypatch.setenv("SEF_BILLING", "off")
    off = await asyncio.to_thread(grant.main, [str(primer.id), "7"])

    out, err = capsys.readouterr()
    assert (gave, nobody, off) == (0, 1, 1)
    assert out == "gave 7 credits; the organization now holds 7\n"
    assert "error: no organization has the id" in err
    assert "error: billing is off (SEF_BILLING): storing costs nothing" in err


@pytest.mark.parametrize("count", ["0", "100001", "many"])
def test_the_grant_command_refuses_a_count_it_cannot_give(
    count: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as stopped:
        grant.main([str(uuid.uuid4()), count])

    assert stopped.value.code == 2
    assert "count" in capsys.readouterr().err


async def test_a_grant_gives_at_least_one_credit(session: AsyncSession, primer: Office) -> None:
    with pytest.raises(ValueError, match="at least one credit"):
        await ledger.grant(session, primer.organization.id, ledger.CreditTerms(starting=0), count=0)
