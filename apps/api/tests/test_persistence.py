"""Every change outlives the request that made it.

Each request here runs in a session of its own and commits for real, as in production, so a
service that forgets to commit loses its change with the request and the next request shows it.
"""

from __future__ import annotations

from typing import Any

from argon2 import PasswordHasher
from httpx import AsyncClient
from sqlalchemy import select, update

from sef_api.auth.passwords import hash_password
from sef_api.db import Database
from sef_api.models import Membership, Role, StoredInvoice, User

from .conftest import REPOSITORY_ROOT

PASSWORD = "a long passphrase"
INVOICE = REPOSITORY_ROOT / "fixtures" / "invoices" / "synthetic" / "srb-final-invoice.xml"


async def register(api: AsyncClient) -> dict[str, Any]:
    response = await api.post(
        "/auth/register",
        json={"email": "ana@primer.example", "password": PASSWORD, "organization_name": "Primer"},
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def sign_in(api: AsyncClient, email: str) -> Any:
    return await api.post("/auth/login", json={"email": email, "password": PASSWORD})


def bearer(body: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {body['access_token']}"}


async def add_accountant(database: Database, ana: dict[str, Any]) -> User:
    async with database.sessions() as session:
        milan = User(email="milan@primer.example", password_hash=await hash_password(PASSWORD))
        session.add(milan)
        await session.flush()
        session.add(
            Membership(
                organization_id=ana["organization"]["id"], user_id=milan.id, role=Role.ACCOUNTANT
            )
        )
        await session.commit()
    return milan


async def test_a_registration_is_kept(committed_api: AsyncClient) -> None:
    await register(committed_api)

    signed_in = await sign_in(committed_api, "ana@primer.example")

    assert signed_in.status_code == 200


async def test_a_refresh_and_a_sign_out_are_kept(committed_api: AsyncClient) -> None:
    ana = await register(committed_api)
    renewed = await committed_api.post(
        "/auth/refresh", json={"refresh_token": ana["refresh_token"]}
    )

    replayed = await committed_api.post(
        "/auth/refresh", json={"refresh_token": ana["refresh_token"]}
    )
    second = (await sign_in(committed_api, "ana@primer.example")).json()
    await committed_api.post("/auth/logout", json={"refresh_token": second["refresh_token"]})
    after_sign_out = await committed_api.post(
        "/auth/refresh", json={"refresh_token": second["refresh_token"]}
    )

    assert renewed.status_code == 200
    assert replayed.status_code == 401  # the first refresh spent the token for good
    assert after_sign_out.status_code == 401


async def test_a_renewed_password_hash_is_kept(
    committed_api: AsyncClient, committed_database: Database
) -> None:
    await register(committed_api)
    old = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(PASSWORD)
    async with committed_database.sessions() as session:
        await session.execute(update(User).values(password_hash=old))
        await session.commit()

    await sign_in(committed_api, "ana@primer.example")

    async with committed_database.sessions() as session:
        stored = await session.scalar(select(User.password_hash))
    assert stored is not None
    assert stored.startswith("$argon2id$v=19$m=19456,t=2,p=1$")


async def test_a_change_of_role_is_kept(
    committed_api: AsyncClient, committed_database: Database
) -> None:
    ana = await register(committed_api)
    milan = await add_accountant(committed_database, ana)

    await committed_api.patch(f"/members/{milan.id}", json={"role": "client"}, headers=bearer(ana))

    listed = (await committed_api.get("/members", headers=bearer(ana))).json()
    assert ("milan@primer.example", "client") in [
        (item["user"]["email"], item["role"]) for item in listed
    ]


async def test_a_removal_is_kept_and_ends_the_members_session(
    committed_api: AsyncClient, committed_database: Database
) -> None:
    ana = await register(committed_api)
    await add_accountant(committed_database, ana)
    milan = (await sign_in(committed_api, "milan@primer.example")).json()

    removed = await committed_api.delete(f"/members/{milan['user']['id']}", headers=bearer(ana))

    assert removed.status_code == 204
    listed = (await committed_api.get("/members", headers=bearer(ana))).json()
    assert [item["user"]["email"] for item in listed] == ["ana@primer.example"]
    refreshed = await committed_api.post(
        "/auth/refresh", json={"refresh_token": milan["refresh_token"]}
    )
    assert refreshed.status_code == 401


async def test_an_invitation_its_acceptance_and_its_revocation_are_kept(
    committed_api: AsyncClient,
) -> None:
    ana = await register(committed_api)
    invited = (
        await committed_api.post(
            "/invitations",
            json={"email": "nova@primer.example", "role": "accountant"},
            headers=bearer(ana),
        )
    ).json()
    revoked = (
        await committed_api.post(
            "/invitations",
            json={"email": "jovana@primer.example", "role": "client"},
            headers=bearer(ana),
        )
    ).json()

    listed = (await committed_api.get("/invitations", headers=bearer(ana))).json()
    joined = await committed_api.post(
        "/auth/accept-invitation", json={"code": invited["code"], "password": PASSWORD}
    )
    await committed_api.delete(f"/invitations/{revoked['id']}", headers=bearer(ana))
    refused = await committed_api.post(
        "/auth/accept-invitation", json={"code": revoked["code"], "password": PASSWORD}
    )

    assert sorted(item["email"] for item in listed) == [
        "jovana@primer.example",
        "nova@primer.example",
    ]
    assert joined.status_code == 200
    assert (await sign_in(committed_api, "nova@primer.example")).status_code == 200
    assert refused.status_code == 400


async def test_the_withdrawal_of_a_removed_owners_invitations_is_kept(
    committed_api: AsyncClient, committed_database: Database
) -> None:
    ana = await register(committed_api)
    milan_user = await add_accountant(committed_database, ana)
    await committed_api.patch(
        f"/members/{milan_user.id}", json={"role": "owner"}, headers=bearer(ana)
    )
    milan = (await sign_in(committed_api, "milan@primer.example")).json()
    issued = (
        await committed_api.post(
            "/invitations",
            json={"email": "milan@ogled.example", "role": "owner"},
            headers=bearer(milan),
        )
    ).json()

    await committed_api.delete(f"/members/{milan_user.id}", headers=bearer(ana))

    assert (await committed_api.get("/invitations", headers=bearer(ana))).json() == []
    refused = await committed_api.post(
        "/auth/accept-invitation", json={"code": issued["code"], "password": PASSWORD}
    )
    assert refused.status_code == 400


async def test_a_stored_invoice_is_kept(
    committed_api: AsyncClient, committed_database: Database
) -> None:
    ana = await register(committed_api)

    response = await committed_api.post(
        "/invoices",
        content=INVOICE.read_bytes(),
        headers={"Content-Type": "application/xml"} | bearer(ana),
    )

    assert response.status_code == 201
    async with committed_database.sessions() as session:
        assert await session.scalar(select(StoredInvoice.content)) == INVOICE.read_bytes()
