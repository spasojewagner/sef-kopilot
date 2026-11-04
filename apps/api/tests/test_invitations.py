"""Invitations on PostgreSQL: issuing a code, listing and revoking, and joining with it."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from argon2 import PasswordHasher
from httpx import AsyncClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.auth import service as auth_service
from sef_api.auth.passwords import hash_password
from sef_api.models import Invitation, Membership, Organization, Role, User

from .factories import Office, bearer, join, office, organization

NEW_PASSWORD = "a long passphrase"


@pytest.fixture
async def primer(session: AsyncSession) -> Office:
    return await office(session, "Primer Računovodstvo", "primer.example")


async def invite(
    api: AsyncClient, primer: Office, email: str = "nova@primer.example", role: str = "accountant"
) -> dict[str, Any]:
    response = await api.post(
        "/invitations", json={"email": email, "role": role}, headers=primer.as_owner()
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def accept(api: AsyncClient, code: str, password: str = NEW_PASSWORD) -> Any:
    return await api.post("/auth/accept-invitation", json={"code": code, "password": password})


# --- issuing -----------------------------------------------------------------------------------


async def test_an_owner_invites_and_sees_the_code_once(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    issued = await invite(api, primer, email="  Nova@Primer.example ")

    assert issued["email"] == "nova@primer.example"
    assert issued["role"] == "accountant"
    assert issued["invited_by"] == str(primer.owner.id)
    lifetime = datetime.fromisoformat(issued["expires_at"]) - datetime.now(UTC)
    assert timedelta(days=7) - timedelta(minutes=1) < lifetime <= timedelta(days=7)
    stored = await session.scalar(select(Invitation))
    assert stored is not None
    assert stored.digest == hashlib.sha256(issued["code"].encode()).hexdigest()
    listed = (await api.get("/invitations", headers=primer.as_owner())).json()
    assert listed == [{key: value for key, value in issued.items() if key != "code"}]


async def test_no_cache_may_keep_an_invitation_code_or_the_tokens_it_buys(
    api: AsyncClient, primer: Office
) -> None:
    invited = await api.post(
        "/invitations",
        json={"email": "nova@primer.example", "role": "client"},
        headers=primer.as_owner(),
    )
    joined = await accept(api, invited.json()["code"])

    for answer in (invited, joined):
        assert answer.is_success, answer.text
        assert answer.headers.get("Cache-Control") == "no-store", answer.url


@pytest.mark.parametrize("caller", ["accountant", "client"])
async def test_only_owners_invite_and_see_invitations(
    api: AsyncClient, primer: Office, caller: str
) -> None:
    headers = primer.as_accountant() if caller == "accountant" else primer.as_client()

    invited = await api.post(
        "/invitations", json={"email": "nova@primer.example", "role": "owner"}, headers=headers
    )
    listed = await api.get("/invitations", headers=headers)

    assert (invited.status_code, listed.status_code) == (403, 403)


async def test_a_member_is_not_invited_again(api: AsyncClient, primer: Office) -> None:
    response = await api.post(
        "/invitations",
        json={"email": "Client@primer.example", "role": "accountant"},
        headers=primer.as_owner(),
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "the address belongs to a member of this organization"}


async def test_inviting_an_address_again_replaces_its_open_invitation(
    api: AsyncClient, primer: Office
) -> None:
    first = await invite(api, primer, role="client")
    second = await invite(api, primer, role="accountant")

    listed = (await api.get("/invitations", headers=primer.as_owner())).json()

    assert [item["id"] for item in listed] == [second["id"]]
    assert (await accept(api, first["code"])).status_code == 400
    assert (await accept(api, second["code"])).json()["role"] == "accountant"


@pytest.mark.parametrize(
    "body",
    [{"email": "not an address", "role": "client"}, {"email": "nova@primer.example", "role": "x"}],
    ids=["address", "role"],
)
async def test_an_invitation_needs_an_address_and_a_role(
    api: AsyncClient, primer: Office, body: dict[str, str]
) -> None:
    response = await api.post("/invitations", json=body, headers=primer.as_owner())

    assert response.status_code == 422


# --- joining -----------------------------------------------------------------------------------


async def test_a_new_person_joins_with_the_code_and_a_password(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    issued = await invite(api, primer)

    response = await accept(api, issued["code"])

    assert response.status_code == 200
    body = response.json()
    assert (body["user"]["email"], body["role"]) == ("nova@primer.example", "accountant")
    assert body["organization"]["id"] == str(primer.organization.id)
    user = await session.scalar(select(User).where(User.email == "nova@primer.example"))
    assert user is not None
    assert user.password_hash.startswith("$argon2id$")
    me = await api.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.json()["role"] == "accountant"
    signed_in = await api.post(
        "/auth/login",
        json={
            "email": "nova@primer.example",
            "password": NEW_PASSWORD,
            "organization_id": str(primer.organization.id),
        },
    )
    assert signed_in.status_code == 200


async def test_a_person_with_an_account_joins_with_its_password(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    elsewhere = await organization(session, "Ogled")
    existing = User(email="milan@ogled.example", password_hash=await hash_password(NEW_PASSWORD))
    session.add(existing)
    await session.flush()
    await join(session, elsewhere, existing, Role.OWNER)
    issued = await invite(api, primer, email="milan@ogled.example", role="client")

    wrong = await accept(api, issued["code"], password="not the password")
    right = await accept(api, issued["code"])

    assert wrong.status_code == 401
    assert wrong.json() == {"detail": "wrong password for the invited address's account"}
    assert right.status_code == 200
    assert (right.json()["organization"]["name"], right.json()["role"]) == (
        "Primer Računovodstvo",
        "client",
    )
    roles = await session.scalars(
        select(Membership.role).where(Membership.user_id == existing.id).order_by(Membership.role)
    )
    assert list(roles) == [Role.CLIENT, Role.OWNER]  # alphabetical: the role is VARCHAR


async def test_a_code_is_good_once(api: AsyncClient, primer: Office) -> None:
    issued = await invite(api, primer)
    await accept(api, issued["code"])

    again = await accept(api, issued["code"])

    assert again.status_code == 400
    assert again.json() == {"detail": "invalid, expired or already used invitation code"}
    assert (await api.get("/invitations", headers=primer.as_owner())).json() == []


@pytest.mark.parametrize("closed_by", ["expiry", "revocation"])
async def test_an_expired_or_revoked_code_does_not_work(
    api: AsyncClient, session: AsyncSession, primer: Office, closed_by: str
) -> None:
    issued = await invite(api, primer)
    if closed_by == "expiry":
        await session.execute(
            update(Invitation).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    else:
        revoked = await api.delete(f"/invitations/{issued['id']}", headers=primer.as_owner())
        assert revoked.status_code == 204

    response = await accept(api, issued["code"])

    assert response.status_code == 400
    assert (await api.get("/invitations", headers=primer.as_owner())).json() == []


async def test_an_unknown_code_does_not_work(api: AsyncClient) -> None:
    assert (await accept(api, "not-an-invitation-code")).status_code == 400


async def test_a_new_accounts_password_needs_twelve_characters(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    issued = await invite(api, primer)

    response = await accept(api, issued["code"], password="too short")

    assert response.status_code == 422
    assert response.json() == {"detail": "a new account's password needs 12 to 128 characters"}
    assert await session.scalar(select(User).where(User.email == "nova@primer.example")) is None
    assert len((await api.get("/invitations", headers=primer.as_owner())).json()) == 1


async def test_a_deactivated_account_cannot_join(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    existing = User(
        email="milan@ogled.example",
        password_hash=await hash_password(NEW_PASSWORD),
        is_active=False,
    )
    session.add(existing)
    await session.flush()
    issued = await invite(api, primer, email="milan@ogled.example")

    assert (await accept(api, issued["code"])).status_code == 401


async def test_a_member_who_joins_again_keeps_the_role(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    issued = await invite(api, primer, email="nova@primer.example", role="owner")
    nova = User(email="nova@primer.example", password_hash=await hash_password(NEW_PASSWORD))
    session.add(nova)
    await session.flush()
    await join(session, primer.organization, nova, Role.CLIENT)  # joined meanwhile

    response = await accept(api, issued["code"])

    assert response.json()["role"] == "client"
    members = select(func.count()).select_from(Membership).where(Membership.user_id == nova.id)
    assert await session.scalar(members) == 1


# --- revoking ----------------------------------------------------------------------------------


async def test_revoking_twice_changes_nothing(api: AsyncClient, primer: Office) -> None:
    issued = await invite(api, primer)

    first = await api.delete(f"/invitations/{issued['id']}", headers=primer.as_owner())
    second = await api.delete(f"/invitations/{issued['id']}", headers=primer.as_owner())

    assert (first.status_code, second.status_code) == (204, 204)


async def test_an_accepted_invitation_cannot_be_revoked(api: AsyncClient, primer: Office) -> None:
    issued = await invite(api, primer)
    await accept(api, issued["code"])

    response = await api.delete(f"/invitations/{issued['id']}", headers=primer.as_owner())

    assert response.status_code == 409
    assert response.json() == {
        "detail": "the invitation has been accepted; remove the member instead"
    }


async def test_an_unknown_invitation_is_not_found(api: AsyncClient, primer: Office) -> None:
    response = await api.delete(
        "/invitations/00000000-0000-4000-8000-000000000000", headers=primer.as_owner()
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "no such invitation in this organization"}


@pytest.mark.parametrize("ended_by", ["removal", "demotion", "deactivation"])
async def test_an_invitation_stops_working_when_its_issuer_may_no_longer_invite(
    api: AsyncClient, session: AsyncSession, primer: Office, ended_by: str
) -> None:
    """Otherwise a removed owner could come back through an owner invitation issued before."""
    milan = primer.accountant
    await session.execute(
        update(Membership).where(Membership.user_id == milan.id).values(role=Role.OWNER)
    )
    issued = await api.post(
        "/invitations",
        json={"email": "milan@ogled.example", "role": "owner"},
        headers=bearer(milan, primer.organization, Role.OWNER),
    )
    if ended_by == "removal":
        await api.delete(f"/members/{milan.id}", headers=primer.as_owner())
    elif ended_by == "demotion":
        await api.patch(f"/members/{milan.id}", json={"role": "client"}, headers=primer.as_owner())
    else:
        await session.execute(update(User).where(User.id == milan.id).values(is_active=False))

    response = await accept(api, issued.json()["code"])

    assert response.status_code == 400
    if ended_by != "deactivation":  # withdrawn, not only refused
        assert (await api.get("/invitations", headers=primer.as_owner())).json() == []


async def test_an_invitation_whose_issuer_was_deleted_does_not_work(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    milan = primer.accountant
    await session.execute(
        update(Membership).where(Membership.user_id == milan.id).values(role=Role.OWNER)
    )
    issued = await api.post(
        "/invitations",
        json={"email": "nova@primer.example", "role": "client"},
        headers=bearer(milan, primer.organization, Role.OWNER),
    )
    await session.execute(delete(User).where(User.id == milan.id))  # invited_by becomes NULL

    assert (await accept(api, issued.json()["code"])).status_code == 400


async def test_only_the_departing_owners_invitations_are_withdrawn(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    milan = primer.accountant
    await session.execute(
        update(Membership).where(Membership.user_id == milan.id).values(role=Role.OWNER)
    )
    anas = await invite(api, primer, email="nova@primer.example")

    await api.delete(f"/members/{milan.id}", headers=primer.as_owner())

    assert (await accept(api, anas["code"])).status_code == 200


async def test_openapi_documents_the_invitations(client: AsyncClient) -> None:
    paths = (await client.get("/openapi.json")).json()["paths"]

    assert paths["/invitations"]["post"]["tags"] == ["members"]
    assert paths["/invitations"]["post"]["security"] == [{"access token or API key": []}]
    assert "security" not in paths["/auth/accept-invitation"]["post"]


async def test_the_organization_of_an_invitation_is_the_one_joined(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    ogled = await office(session, "Ogled", "ogled.example")
    issued = await api.post(
        "/invitations",
        json={"email": "nova@primer.example", "role": "client"},
        headers=ogled.as_owner(),
    )

    joined = await accept(api, issued.json()["code"])

    assert joined.json()["organization"]["name"] == "Ogled"
    primer_members = (await api.get("/members", headers=primer.as_owner())).json()
    assert "nova@primer.example" not in [item["user"]["email"] for item in primer_members]
    assert await session.get(Organization, ogled.organization.id) is not None


async def test_joining_renews_a_hash_made_with_old_parameters(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    old = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(NEW_PASSWORD)
    session.add(User(email="milan@ogled.example", password_hash=old))
    await session.flush()
    issued = await invite(api, primer, email="milan@ogled.example")

    await accept(api, issued["code"])

    renewed = await session.scalar(
        select(User.password_hash).where(User.email == "milan@ogled.example")
    )
    assert renewed is not None
    assert renewed.startswith("$argon2id$v=19$m=19456,t=2,p=1$")


async def test_an_address_that_registers_while_joining_is_told_to_use_its_password(
    api: AsyncClient,
    session: AsyncSession,
    primer: Office,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issued = await invite(api, primer)

    async def registers_meanwhile(password: str) -> str:
        session.add(User(email="nova@primer.example", password_hash=await hash_password(password)))
        await session.flush()
        return await hash_password(password)

    monkeypatch.setattr(auth_service, "hash_password", registers_meanwhile)

    response = await accept(api, issued["code"])

    assert response.status_code == 409
    assert response.json() == {
        "detail": "the invited address has just registered; accept with that account's password"
    }
