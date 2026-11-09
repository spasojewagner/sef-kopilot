"""An organization's credits, where billing is on (ADR-0059): a balance never below zero, even
when two spends race for the last credit; a ledger whose entries add up to the balance; the
operator's grants."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.billing import grant, ledger
from sef_api.db import Database
from sef_api.models import CreditEntry, Organization

from .factories import Office, office


@pytest.fixture
async def primer(session: AsyncSession) -> Office:
    return await office(session, "Primer Računovodstvo", "primer.example")


async def ledger_sum(session: AsyncSession, organization: Organization) -> int:
    return (
        await session.scalar(
            select(func.coalesce(func.sum(CreditEntry.delta), 0)).where(
                CreditEntry.organization_id == organization.id
            )
        )
        or 0
    )


# --- spending ----------------------------------------------------------------------------------


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
