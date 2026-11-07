"""Rate limits on the API's endpoints: what each counts, by which key, and the answer beyond a
limit (429 with ``Retry-After``)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.auth.passwords import hash_password, verify_password
from sef_api.db import get_session
from sef_api.main import create_app
from sef_api.members import invitations
from sef_api.models import Role, User
from sef_api.rate_limits import DEFAULT_LIMITS, Counted, Limit, RateLimiter

from .conftest import settings_for
from .factories import Office, api_key, join, office, organization
from .test_invoices_validate import VALID, XML, Scripted, application, using
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
    app.state.limits = dict.fromkeys(app.state.limits, TWO_A_MINUTE)
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


# --- failed passwords per e-mail address -------------------------------------------------------

PASSWORD = "a long passphrase"


@pytest.fixture
async def ana(session: AsyncSession) -> User:
    """The owner of Primer, who signs in with ``PASSWORD``."""
    primer = await organization(session, "Primer")
    ana = User(email="ana@primer.example", password_hash=await hash_password(PASSWORD))
    session.add(ana)
    await session.flush()
    await join(session, primer, ana, Role.OWNER)
    return ana


async def sign_in(app: FastAPI, n: int, email: str, password: str) -> Response:
    """A sign-in from an address of its own, so that only the e-mail address's count matters."""
    async with from_address(app, f"192.0.2.{n}") as client:
        return await client.post("/auth/login", json={"email": email, "password": password})


async def test_wrong_passwords_hold_an_account_back_wherever_they_come_from(
    app: FastAPI, ana: User
) -> None:
    wrong = [await sign_in(app, n, "ana@primer.example", "not the password") for n in range(2)]
    right = await sign_in(app, 2, " ANA@Primer.example", PASSWORD)

    assert [answer.status_code for answer in wrong] == [401, 401]
    assert (right.status_code, right.json()) == (
        429,
        {"detail": "too many failed passwords for this e-mail address; try again in 30 s"},
    )
    assert right.headers["Retry-After"] == "30"


async def test_an_address_without_an_account_is_held_back_alike(app: FastAPI) -> None:
    answers = [await sign_in(app, n, "nobody@primer.example", "a guess") for n in range(3)]

    assert [answer.status_code for answer in answers] == [401, 401, 429]


async def test_the_right_password_starts_the_count_afresh(app: FastAPI, ana: User) -> None:
    passwords = ["wrong", PASSWORD, "wrong", "wrong", PASSWORD]

    answers = [await sign_in(app, n, "ana@primer.example", p) for n, p in enumerate(passwords)]

    assert [answer.status_code for answer in answers] == [401, 200, 401, 401, 429]


async def test_no_password_is_checked_while_an_account_is_held_back(
    app: FastAPI, ana: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A held-back guess costs no password hash, and its answer cannot tell right from wrong."""
    checked: list[str] = []

    async def counting(password_hash: str | None, password: str) -> bool:
        checked.append(password)
        return await verify_password(password_hash, password)

    monkeypatch.setattr("sef_api.auth.service.verify_password", counting)

    for n in range(4):
        await sign_in(app, n, "ana@primer.example", f"guess {n}")

    assert checked == ["guess 0", "guess 1"]


async def test_accepting_an_invitation_counts_wrong_passwords_with_sign_in(
    app: FastAPI, session: AsyncSession, ana: User
) -> None:
    """Ana is invited to Ogled with her own account: holding an invitation's code must not let
    anyone guess at her password where signing in would hold them back."""
    ogled = await office(session, "Ogled", "ogled.example")
    issued = await invitations.invite(
        session, ogled.organization.id, ogled.owner.id, email=ana.email, role=Role.ACCOUNTANT
    )

    wrong = await sign_in(app, 0, ana.email, "not the password")
    async with from_address(app, "192.0.2.1") as client:
        joining = await client.post(
            "/auth/accept-invitation", json={"code": issued.code, "password": "a guess"}
        )
        held = await client.post(
            "/auth/accept-invitation", json={"code": issued.code, "password": PASSWORD}
        )

    assert (wrong.status_code, joining.status_code, held.status_code) == (401, 401, 429)
    assert held.json() == {
        "detail": "too many failed passwords for this e-mail address; try again in 30 s"
    }


# --- validations per caller and per organization -----------------------------------------------


@pytest.fixture
async def primer(session: AsyncSession) -> Office:
    return await office(session, "Primer Računovodstvo", "primer.example")


def validating(
    session: AsyncSession, *, caller: int, organization: int
) -> AbstractAsyncContextManager[AsyncClient]:
    """An application that allows ``caller`` validations a minute to each caller and
    ``organization`` to each organization, with a validator that answers at once."""
    return application(
        session,
        using(Scripted()),
        SEF_VALIDATIONS_PER_MINUTE=str(caller),
        SEF_ORGANIZATION_VALIDATIONS_PER_MINUTE=str(organization),
    )


async def validate(api: AsyncClient, caller: dict[str, str], content: bytes = VALID) -> Response:
    return await api.post("/invoices/validate", content=content, headers=XML | caller)


async def test_a_caller_gets_the_validations_a_minute_the_settings_allow(
    session: AsyncSession, primer: Office
) -> None:
    async with validating(session, caller=2, organization=100) as api:
        answers = [await validate(api, primer.as_client()) for _ in range(3)]

    assert [answer.status_code for answer in answers] == [200, 200, 429]
    assert answers[2].json() == {"detail": "too many validations; try again in 30 s"}
    assert answers[2].headers["Retry-After"] == "30"


async def test_the_callers_of_an_organization_share_its_count(
    session: AsyncSession, primer: Office
) -> None:
    ogled = await office(session, "Ogled", "ogled.example")

    async with validating(session, caller=10, organization=3) as api:
        for caller in (primer.as_client(), primer.as_client(), primer.as_accountant()):
            await validate(api, caller)
        held = await validate(api, primer.as_owner())
        elsewhere = await validate(api, ogled.as_owner())

    assert (held.status_code, held.json()) == (
        429,
        {"detail": "too many validations in this organization; try again in 20 s"},
    )
    assert elsewhere.status_code == 200


async def test_each_api_key_is_a_caller_of_its_own(session: AsyncSession, primer: Office) -> None:
    pantheon = await api_key(session, primer.organization, primer.client)
    minimax = await api_key(session, primer.organization, primer.client)

    async with validating(session, caller=1, organization=100) as api:
        answers = [
            await validate(api, caller)
            for caller in (primer.as_client(), pantheon.header(), minimax.header())
        ]
        held = await validate(api, pantheon.header())

    assert [answer.status_code for answer in answers] == [200, 200, 200]
    assert held.status_code == 429


async def test_storing_an_invoice_counts_as_a_validation(
    session: AsyncSession, primer: Office
) -> None:
    async with validating(session, caller=2, organization=100) as api:
        validated = await validate(api, primer.as_client())
        stored = await api.post("/invoices", content=VALID, headers=XML | primer.as_client())
        held = await api.post("/invoices", content=VALID, headers=XML | primer.as_client())

    assert (validated.status_code, stored.status_code, held.status_code) == (200, 201, 429)


async def test_a_caller_held_back_is_answered_before_the_body_is_read(
    session: AsyncSession, primer: Office
) -> None:
    """A body beyond the size limit would answer 413 if it were read."""
    async with validating(session, caller=1, organization=100) as api:
        await validate(api, primer.as_client())
        held = await validate(api, primer.as_client(), b"x" * (6 * 1024 * 1024))

    assert held.status_code == 429


def test_the_default_limits() -> None:
    """Per address, generous enough for an office of people behind one address and tight
    enough to stop a script, an MCP client's registration among them; per e-mail address, ten
    wrong passwords in a quarter of an hour."""
    assert dict(DEFAULT_LIMITS) == {
        Counted.SIGN_IN: Limit(30, timedelta(minutes=1)),
        Counted.REGISTRATION: Limit(10, timedelta(hours=1)),
        Counted.REFRESH: Limit(60, timedelta(minutes=1)),
        Counted.INVITATION: Limit(10, timedelta(minutes=1)),
        Counted.FAILED_PASSWORD: Limit(10, timedelta(minutes=15)),
        Counted.CLIENT_REGISTRATION: Limit(10, timedelta(hours=1)),
    }


async def test_openapi_documents_the_429_of_every_limited_endpoint(client: AsyncClient) -> None:
    paths = (await client.get("/openapi.json")).json()["paths"]

    for _, path, _ in LIMITED.values():
        assert "429" in paths[path]["post"]["responses"], path
