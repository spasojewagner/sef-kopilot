"""Rate limits on the API's endpoints: what each counts, by which key, and the answer beyond a
limit (429 with ``Retry-After``)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.db import get_session
from sef_api.main import create_app
from sef_api.rate_limits import DEFAULT_LIMITS, Counted, Limit, RateLimiter

from .conftest import settings_for
from .test_rate_limits import Clock

#: Two requests a minute: what every per-address limit allows in these tests.
TWO_A_MINUTE = Limit(2, timedelta(minutes=1))
CLIENT = "203.0.113.7"
NEIGHBOUR = "198.51.100.4"


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
async def app(session: AsyncSession, clock: Clock) -> AsyncIterator[FastAPI]:
    """An application on the test's session whose limits allow two requests a minute, on a
    clock the test moves."""
    app = create_app(settings_for())

    async def the_test_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = the_test_session
    app.state.limiter = RateLimiter(clock=clock)
    app.state.limits = dict.fromkeys(DEFAULT_LIMITS, TWO_A_MINUTE)
    yield app
    await app.state.database.engine.dispose()


@asynccontextmanager
async def from_address(app: FastAPI, address: str) -> AsyncIterator[AsyncClient]:
    """A client of ``app`` whose requests come from ``address``."""
    transport = ASGITransport(app=app, client=(address, 50_000))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def registration(n: int) -> dict[str, Any]:
    return {
        "email": f"ana{n}@primer.example",
        "password": "a long passphrase",
        "organization_name": f"Primer {n}",
    }


#: Each limited endpoint, what it counts, and a request for it.
LIMITED: dict[str, tuple[Counted, str, Callable[[int], dict[str, Any]]]] = {
    "sign-in": (
        Counted.SIGN_IN,
        "/auth/login",
        lambda n: {"email": f"ana{n}@primer.example", "password": "not the password"},
    ),
    "registration": (Counted.REGISTRATION, "/auth/register", registration),
    "invitation": (
        Counted.INVITATION,
        "/auth/accept-invitation",
        lambda n: {"code": f"not-a-code-{n}", "password": "a long passphrase"},
    ),
    "refresh": (Counted.REFRESH, "/auth/refresh", lambda n: {"refresh_token": f"unknown-{n}"}),
    "sign-out": (Counted.REFRESH, "/auth/logout", lambda n: {"refresh_token": f"unknown-{n}"}),
}


@pytest.mark.parametrize("endpoint", sorted(LIMITED))
async def test_an_address_gets_what_the_limit_allows_then_429_with_retry_after(
    app: FastAPI, endpoint: str
) -> None:
    counted, path, body = LIMITED[endpoint]

    async with from_address(app, CLIENT) as client:
        allowed = [await client.post(path, json=body(n)) for n in range(2)]
        refused = await client.post(path, json=body(2))

    assert all(answer.status_code != 429 for answer in allowed)
    assert refused.status_code == 429
    assert refused.json() == {"detail": f"too many {counted}; try again in 30 s"}
    assert refused.headers["Retry-After"] == "30"


async def test_each_address_is_counted_apart(app: FastAPI) -> None:
    _, path, body = LIMITED["sign-in"]

    async with from_address(app, CLIENT) as client, from_address(app, NEIGHBOUR) as neighbour:
        for n in range(2):
            await client.post(path, json=body(n))
        refused = await client.post(path, json=body(2))
        elsewhere = await neighbour.post(path, json=body(3))

    assert (refused.status_code, elsewhere.status_code) == (429, 401)


async def test_a_header_the_client_writes_does_not_change_its_address(app: FastAPI) -> None:
    """``X-Forwarded-For`` is a proxy's to set; the server trusts only the proxies it is told
    to (uvicorn's ``--forwarded-allow-ips``), and a client cannot pose as another address."""
    _, path, body = LIMITED["sign-in"]

    async with from_address(app, CLIENT) as client:
        answers = [
            await client.post(path, json=body(n), headers={"X-Forwarded-For": f"192.0.2.{n}"})
            for n in range(3)
        ]

    assert [answer.status_code for answer in answers] == [401, 401, 429]


async def test_the_endpoints_count_their_own_limits_and_sign_out_counts_with_refresh(
    app: FastAPI,
) -> None:
    async with from_address(app, CLIENT) as client:
        for n in range(2):
            await client.post("/auth/refresh", json={"refresh_token": f"unknown-{n}"})
        signing_out = await client.post("/auth/logout", json={"refresh_token": "unknown"})
        signing_in = await client.post(
            "/auth/login", json={"email": "ana@primer.example", "password": "not the password"}
        )

    assert (signing_out.status_code, signing_in.status_code) == (429, 401)


async def test_a_client_that_waits_as_retry_after_says_is_served(
    app: FastAPI, clock: Clock
) -> None:
    _, path, body = LIMITED["registration"]

    async with from_address(app, CLIENT) as client:
        for n in range(2):
            await client.post(path, json=body(n))
        refused = await client.post(path, json=body(2))
        clock.advance(int(refused.headers["Retry-After"]))
        served = await client.post(path, json=body(3))

    assert (refused.status_code, served.status_code) == (429, 201)


def test_the_limits_per_address() -> None:
    """Generous enough for an office of people behind one address, tight enough to stop a
    script."""
    assert dict(DEFAULT_LIMITS) == {
        Counted.SIGN_IN: Limit(30, timedelta(minutes=1)),
        Counted.REGISTRATION: Limit(10, timedelta(hours=1)),
        Counted.REFRESH: Limit(60, timedelta(minutes=1)),
        Counted.INVITATION: Limit(10, timedelta(minutes=1)),
    }


async def test_openapi_documents_the_429_of_every_limited_endpoint(client: AsyncClient) -> None:
    paths = (await client.get("/openapi.json")).json()["paths"]

    for _, path, _ in LIMITED.values():
        assert "429" in paths[path]["post"]["responses"], path
