"""When each API key was last used: written at most once a minute, listed with the keys, and
logged as a security event when it is written."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.api_keys import service
from sef_api.logs import SECURITY
from sef_api.models import ApiKey

from .factories import Office, api_key, office
from .test_mcp import POSTED, Served, initialize, served

__all__ = ["served"]  # the fixture, shared with test_mcp


@pytest.fixture
async def primer(session: AsyncSession) -> Office:
    return await office(session, "Primer Računovodstvo", "primer.example")


def used(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    return [
        dict(getattr(record, "fields", {}))
        for record in caplog.records
        if record.name == SECURITY.name and getattr(record, "event", None) == "api-key.used"
    ]


async def last_used(session: AsyncSession, key_id: object) -> datetime | None:
    return await session.scalar(
        select(ApiKey.last_used_at)
        .where(ApiKey.id == key_id)
        .execution_options(populate_existing=True)
    )


async def test_a_keys_use_is_written_once_a_minute_and_listed(
    api: AsyncClient, session: AsyncSession, primer: Office, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=SECURITY.name)
    key = await api_key(session, primer.organization, primer.client)
    before = datetime.now(UTC)

    first = await api.get("/invoices", headers=key.header())
    noted = await last_used(session, key.row.id)
    again = await api.get("/invoices", headers=key.header())
    still = await last_used(session, key.row.id)
    listed = (await api.get("/api-keys", headers=primer.as_client())).json()

    assert (first.status_code, again.status_code) == (200, 200)
    assert noted is not None
    assert before <= noted <= datetime.now(UTC)
    # A second request within the minute writes nothing and logs nothing.
    assert still == noted
    assert used(caplog) == [
        {
            "key": str(key.row.id),
            "user": str(primer.client.id),
            "organization": str(primer.organization.id),
        }
    ]
    (shown,) = listed
    assert datetime.fromisoformat(shown["last_used_at"]) == noted


async def test_a_minute_later_the_use_is_written_again(
    api: AsyncClient, session: AsyncSession, primer: Office, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=SECURITY.name)
    key = await api_key(session, primer.organization, primer.client)
    await api.get("/invoices", headers=key.header())
    earlier = datetime.now(UTC) - service.USED_EVERY - timedelta(seconds=1)
    await session.execute(
        update(ApiKey).where(ApiKey.id == key.row.id).values(last_used_at=earlier)
    )

    await api.get("/invoices", headers=key.header())

    noted = await last_used(session, key.row.id)
    assert noted is not None
    assert noted > earlier + service.USED_EVERY
    assert len(used(caplog)) == 2


async def test_a_key_that_does_not_work_is_not_noted(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    key = await api_key(session, primer.organization, primer.client)
    await session.execute(
        update(ApiKey).where(ApiKey.id == key.row.id).values(revoked_at=datetime.now(UTC))
    )

    refused = await api.get("/invoices", headers=key.header())

    assert refused.status_code == 401
    assert await last_used(session, key.row.id) is None


async def test_a_key_used_at_the_mcp_endpoint_is_noted(served: Served) -> None:
    async with served.http(served.key.header() | POSTED) as http:
        answered = await http.post("/mcp", json=initialize())
    database = served.app.state.database
    async with database.sessions() as session:
        noted = await last_used(session, served.key.row.id)

    assert answered.status_code == 200
    assert noted is not None
