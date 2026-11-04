"""``/auth`` on PostgreSQL: registration, sign-in, refresh rotation, sign-out, the principal."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from argon2 import PasswordHasher
from httpx import AsyncClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.auth.tokens import issue_access_token
from sef_api.models import Membership, Organization, RefreshToken, Role, User

from .conftest import TEST_JWT_SECRET

PASSWORD = "correct horse battery"
REGISTRATION = {
    "email": "Ana@Primer.example",
    "password": PASSWORD,
    "organization_name": "  Primer Računovodstvo ",
}


async def register(api: AsyncClient, **change: str) -> dict[str, Any]:
    response = await api.post("/auth/register", json=REGISTRATION | change)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def login(api: AsyncClient, **change: Any) -> Any:
    return await api.post(
        "/auth/login", json={"email": "ana@primer.example", "password": PASSWORD} | change
    )


async def refresh(api: AsyncClient, token: str) -> Any:
    return await api.post("/auth/refresh", json={"refresh_token": token})


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- registration ------------------------------------------------------------------------------


async def test_registration_creates_the_account_its_organization_and_an_owner(
    api: AsyncClient, session: AsyncSession
) -> None:
    body = await register(api)

    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == "ana@primer.example"
    assert body["organization"]["name"] == "Primer Računovodstvo"
    assert body["role"] == "owner"
    assert 895 <= body["expires_in"] <= 900
    assert 30 * 86400 - 5 <= body["refresh_expires_in"] <= 30 * 86400
    membership = await session.scalar(select(Membership))
    assert membership is not None
    assert membership.role is Role.OWNER


async def test_the_database_keeps_neither_the_password_nor_the_refresh_token(
    api: AsyncClient, session: AsyncSession
) -> None:
    body = await register(api)

    user = await session.scalar(select(User))
    stored = await session.scalar(select(RefreshToken))
    assert user is not None
    assert stored is not None
    assert user.password_hash.startswith("$argon2id$")
    assert PASSWORD not in user.password_hash
    assert stored.digest == hashlib.sha256(body["refresh_token"].encode()).hexdigest()


async def test_an_e_mail_address_registers_once_whatever_its_case(api: AsyncClient) -> None:
    await register(api)

    response = await api.post("/auth/register", json=REGISTRATION | {"email": "ANA@primer.example"})

    assert response.status_code == 409
    assert response.json() == {"detail": "an account with this e-mail address exists already"}


@pytest.mark.parametrize(
    "change",
    [
        {"password": "too short"},
        {"password": "x" * 129},
        {"email": "not an address"},
        {"organization_name": "   "},
        {"organization_name": "x" * 201},
    ],
    ids=["short password", "long password", "bad e-mail", "blank name", "long name"],
)
async def test_registration_checks_its_input(api: AsyncClient, change: dict[str, str]) -> None:
    response = await api.post("/auth/register", json=REGISTRATION | change)

    assert response.status_code == 422


# --- sign-in -----------------------------------------------------------------------------------


async def test_signing_in_gives_tokens_for_the_only_organization(api: AsyncClient) -> None:
    registered = await register(api)

    response = await login(api, email="  ANA@Primer.example ")

    assert response.status_code == 200
    assert response.json()["organization"] == registered["organization"]
    assert response.json()["role"] == "owner"


async def test_no_cache_may_keep_an_answer_that_carries_tokens(api: AsyncClient) -> None:
    registered = await api.post("/auth/register", json=REGISTRATION)
    signed_in = await login(api)
    renewed = await refresh(api, signed_in.json()["refresh_token"])

    for answer in (registered, signed_in, renewed):
        assert answer.is_success, answer.text
        assert answer.headers.get("Cache-Control") == "no-store", answer.url


async def test_a_wrong_password_and_an_unknown_address_get_the_same_answer(
    api: AsyncClient,
) -> None:
    await register(api)

    wrong_password = await login(api, password="not the password")
    unknown_address = await login(api, email="nobody@primer.example")

    for response in (wrong_password, unknown_address):
        assert response.status_code == 401
        assert response.json() == {"detail": "invalid e-mail address or password"}
        assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_a_hash_with_old_parameters_is_renewed_at_sign_in(
    api: AsyncClient, session: AsyncSession
) -> None:
    await register(api)
    old = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(PASSWORD)
    await session.execute(update(User).values(password_hash=old))

    response = await login(api)

    user = await session.scalar(select(User))
    assert response.status_code == 200
    assert user is not None
    assert user.password_hash != old
    assert user.password_hash.startswith("$argon2id$v=19$m=19456,t=2,p=1$")


async def test_a_deactivated_account_cannot_sign_in(
    api: AsyncClient, session: AsyncSession
) -> None:
    await register(api)
    await session.execute(update(User).values(is_active=False))

    response = await login(api)

    assert response.status_code == 401


async def test_a_member_of_several_organizations_chooses_one(
    api: AsyncClient, session: AsyncSession
) -> None:
    registered = await register(api)
    other = Organization(name="Ogledni Kupac")
    session.add(other)
    await session.flush()
    session.add(
        Membership(
            organization_id=other.id,
            user_id=uuid.UUID(registered["user"]["id"]),
            role=Role.ACCOUNTANT,
        )
    )
    await session.flush()

    unchosen = await login(api)
    chosen = await login(api, organization_id=str(other.id))

    assert unchosen.status_code == 409
    assert [
        (item["organization"]["name"], item["role"]) for item in unchosen.json()["organizations"]
    ] == [("Ogledni Kupac", "accountant"), ("Primer Računovodstvo", "owner")]
    assert chosen.status_code == 200
    assert (chosen.json()["organization"]["id"], chosen.json()["role"]) == (
        str(other.id),
        "accountant",
    )


async def test_signing_in_to_someone_elses_organization_is_forbidden(api: AsyncClient) -> None:
    await register(api)
    theirs = await register(api, email="milan@ogled.example", organization_name="Ogled")

    response = await login(api, organization_id=theirs["organization"]["id"])

    assert response.status_code == 403
    assert response.json() == {"detail": "not a member of this organization"}


async def test_an_account_without_organizations_cannot_sign_in(
    api: AsyncClient, session: AsyncSession
) -> None:
    await register(api)
    await session.execute(delete(Membership))

    response = await login(api)

    assert response.status_code == 403


# --- refresh and sign-out ----------------------------------------------------------------------


async def test_a_refresh_token_buys_one_new_pair(api: AsyncClient) -> None:
    registered = await register(api)

    renewed = await refresh(api, registered["refresh_token"])

    assert renewed.status_code == 200
    assert renewed.json()["refresh_token"] != registered["refresh_token"]
    assert renewed.json()["access_token"] != registered["access_token"]
    assert renewed.json()["organization"] == registered["organization"]


async def test_replaying_a_spent_refresh_token_ends_the_session(
    api: AsyncClient, session: AsyncSession
) -> None:
    registered = await register(api)
    renewed = (await refresh(api, registered["refresh_token"])).json()

    replayed = await refresh(api, registered["refresh_token"])
    after = await refresh(api, renewed["refresh_token"])

    assert replayed.status_code == 401
    assert replayed.json() == {"detail": "invalid or expired refresh token"}
    assert after.status_code == 401
    revoked = select(func.count()).where(RefreshToken.revoked_at.is_not(None))
    assert await session.scalar(revoked) == 2


async def test_sessions_are_independent(api: AsyncClient) -> None:
    first = await register(api)
    second = (await login(api)).json()

    await refresh(api, first["refresh_token"])
    await refresh(api, first["refresh_token"])  # replayed: ends the first session only

    assert (await refresh(api, second["refresh_token"])).status_code == 200


async def test_an_expired_refresh_token_is_refused(api: AsyncClient, session: AsyncSession) -> None:
    registered = await register(api)
    await session.execute(
        update(RefreshToken).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )

    response = await refresh(api, registered["refresh_token"])

    assert response.status_code == 401


async def test_an_unknown_refresh_token_is_refused(api: AsyncClient) -> None:
    assert (await refresh(api, "not-a-refresh-token")).status_code == 401


async def test_a_change_of_role_reaches_the_next_access_token(
    api: AsyncClient, session: AsyncSession
) -> None:
    registered = await register(api)
    await session.execute(update(Membership).values(role=Role.CLIENT))

    renewed = (await refresh(api, registered["refresh_token"])).json()
    me = await api.get("/auth/me", headers=bearer(renewed["access_token"]))

    assert renewed["role"] == "client"
    assert me.json()["role"] == "client"


@pytest.mark.parametrize("ended_by", ["deactivation", "removal from the organization"])
async def test_a_session_ends_when_the_person_may_no_longer_sign_in(
    api: AsyncClient, session: AsyncSession, ended_by: str
) -> None:
    registered = await register(api)
    if ended_by == "deactivation":
        await session.execute(update(User).values(is_active=False))
    else:
        await session.execute(delete(Membership))

    response = await refresh(api, registered["refresh_token"])

    assert response.status_code == 401
    assert await session.scalar(select(func.count()).where(RefreshToken.revoked_at.is_(None))) == 0


async def test_signing_out_ends_the_session(api: AsyncClient) -> None:
    registered = await register(api)

    signed_out = await api.post("/auth/logout", json={"refresh_token": registered["refresh_token"]})

    assert signed_out.status_code == 204
    assert (await refresh(api, registered["refresh_token"])).status_code == 401


async def test_signing_out_with_an_unknown_token_changes_nothing(api: AsyncClient) -> None:
    response = await api.post("/auth/logout", json={"refresh_token": "never-issued"})

    assert response.status_code == 204


# --- the principal -----------------------------------------------------------------------------


async def test_an_access_token_says_who_is_calling(api: AsyncClient) -> None:
    registered = await register(api)

    response = await api.get("/auth/me", headers=bearer(registered["access_token"]))

    assert response.status_code == 200
    assert response.json() == {
        "user": registered["user"],
        "organization": registered["organization"],
        "role": "owner",
    }


async def test_without_an_access_token_the_answer_is_401(api: AsyncClient) -> None:
    response = await api.get("/auth/me")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize("token", ["not.a.token", "expired"])
async def test_an_invalid_or_expired_access_token_is_401(api: AsyncClient, token: str) -> None:
    if token == "expired":
        token, _ = issue_access_token(
            uuid.uuid4(),
            uuid.uuid4(),
            Role.OWNER,
            secret=TEST_JWT_SECRET,
            lifetime=timedelta(minutes=15),
            now=datetime.now(UTC) - timedelta(hours=1),
        )

    response = await api.get("/auth/me", headers=bearer(token))

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == 'Bearer error="invalid_token"'


async def test_who_am_i_reports_the_role_held_now(api: AsyncClient, session: AsyncSession) -> None:
    registered = await register(api)
    await session.execute(update(Membership).values(role=Role.ACCOUNTANT))

    response = await api.get("/auth/me", headers=bearer(registered["access_token"]))

    assert response.json()["role"] == "accountant"  # the token still says "owner"


@pytest.mark.parametrize("ended_by", ["deleting the account", "deactivation", "removal"])
async def test_who_am_i_fails_once_the_account_or_the_membership_has_ended(
    api: AsyncClient, session: AsyncSession, ended_by: str
) -> None:
    registered = await register(api)
    if ended_by == "deleting the account":
        await session.execute(delete(User))
    elif ended_by == "deactivation":
        await session.execute(update(User).values(is_active=False))
    else:
        await session.execute(delete(Membership))

    response = await api.get("/auth/me", headers=bearer(registered["access_token"]))

    assert response.status_code == 401
    assert response.json() == {"detail": "the account or its membership is no longer active"}


async def test_openapi_documents_the_auth_endpoints_and_the_bearer_scheme(
    client: AsyncClient,
) -> None:
    schema = (await client.get("/openapi.json")).json()

    for path in ("/auth/register", "/auth/login", "/auth/refresh", "/auth/logout"):
        assert schema["paths"][path]["post"]["tags"] == ["auth"]
    assert schema["paths"]["/auth/me"]["get"]["security"] == [{"access token or API key": []}]
    assert schema["components"]["securitySchemes"]["access token or API key"]["scheme"] == "bearer"
