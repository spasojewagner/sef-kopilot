"""``/members`` on PostgreSQL: who may see and manage members, the last-owner rule, and how fast a
change reaches the member."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.auth.tokens import new_opaque_token, opaque_token_digest
from sef_api.models import Membership, Organization, RefreshToken, Role, User

from .factories import Office, bearer, join, office


@pytest.fixture
async def primer(session: AsyncSession) -> Office:
    return await office(session, "Primer Računovodstvo", "primer.example")


async def role_of(session: AsyncSession, office: Office, user: User) -> Role | None:
    return await session.scalar(
        select(Membership.role).where(
            Membership.organization_id == office.organization.id, Membership.user_id == user.id
        )
    )


# --- reading -----------------------------------------------------------------------------------


@pytest.mark.parametrize("reader", ["owner", "accountant"])
async def test_owners_and_accountants_see_the_members(
    api: AsyncClient, primer: Office, reader: str
) -> None:
    headers = primer.as_owner() if reader == "owner" else primer.as_accountant()

    response = await api.get("/members", headers=headers)

    assert response.status_code == 200
    assert [(item["user"]["email"], item["role"]) for item in response.json()] == [
        ("accountant@primer.example", "accountant"),
        ("client@primer.example", "client"),
        ("owner@primer.example", "owner"),
    ]


async def test_a_client_does_not_see_the_members(api: AsyncClient, primer: Office) -> None:
    response = await api.get("/members", headers=primer.as_client())

    assert response.status_code == 403
    assert response.json() == {"detail": "requires the permission members:read"}


async def test_without_an_access_token_the_members_are_not_shown(api: AsyncClient) -> None:
    response = await api.get("/members")

    assert response.status_code == 401


# --- changing roles ----------------------------------------------------------------------------


async def test_an_owner_changes_a_members_role(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    response = await api.patch(
        f"/members/{primer.accountant.id}", json={"role": "client"}, headers=primer.as_owner()
    )

    assert response.status_code == 200
    assert response.json()["role"] == "client"
    assert response.json()["user"] == {
        "id": str(primer.accountant.id),
        "email": "accountant@primer.example",
    }
    assert await role_of(session, primer, primer.accountant) is Role.CLIENT


async def test_a_new_role_applies_to_the_members_next_request(
    api: AsyncClient, primer: Office
) -> None:
    before = primer.as_accountant()  # its token still says "accountant" afterwards

    await api.patch(
        f"/members/{primer.accountant.id}", json={"role": "client"}, headers=primer.as_owner()
    )

    assert (await api.get("/members", headers=before)).status_code == 403


@pytest.mark.parametrize("caller", ["accountant", "client"])
async def test_only_owners_manage_members(api: AsyncClient, primer: Office, caller: str) -> None:
    headers = primer.as_accountant() if caller == "accountant" else primer.as_client()

    changed = await api.patch(
        f"/members/{primer.owner.id}", json={"role": "client"}, headers=headers
    )
    removed = await api.delete(f"/members/{primer.owner.id}", headers=headers)

    for response in (changed, removed):
        assert response.status_code == 403
        assert response.json() == {"detail": "requires the permission members:manage"}


async def test_the_last_owner_keeps_the_role(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    demoted = await api.patch(
        f"/members/{primer.owner.id}", json={"role": "accountant"}, headers=primer.as_owner()
    )
    removed = await api.delete(f"/members/{primer.owner.id}", headers=primer.as_owner())

    for response in (demoted, removed):
        assert response.status_code == 409
        assert response.json() == {"detail": "an organization keeps at least one owner"}
    assert await role_of(session, primer, primer.owner) is Role.OWNER


async def test_an_owner_steps_down_while_another_owner_remains(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    await session.execute(
        update(Membership).where(Membership.user_id == primer.accountant.id).values(role=Role.OWNER)
    )

    response = await api.patch(
        f"/members/{primer.owner.id}", json={"role": "accountant"}, headers=primer.as_owner()
    )
    afterwards = await api.patch(
        f"/members/{primer.client.id}", json={"role": "owner"}, headers=primer.as_owner()
    )

    assert response.status_code == 200
    assert afterwards.status_code == 403  # an accountant now, whatever the token says


async def test_a_deactivated_owner_does_not_count_as_the_remaining_one(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    await session.execute(
        update(Membership).where(Membership.user_id == primer.accountant.id).values(role=Role.OWNER)
    )
    await session.execute(
        update(User).where(User.id == primer.accountant.id).values(is_active=False)
    )

    response = await api.patch(
        f"/members/{primer.owner.id}", json={"role": "client"}, headers=primer.as_owner()
    )

    assert response.status_code == 409


async def test_a_role_must_be_one_of_the_three(api: AsyncClient, primer: Office) -> None:
    response = await api.patch(
        f"/members/{primer.client.id}", json={"role": "admin"}, headers=primer.as_owner()
    )

    assert response.status_code == 422


# --- removing ----------------------------------------------------------------------------------


async def test_removing_a_member_ends_their_sessions_at_once(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    session.add(
        RefreshToken(
            organization_id=primer.organization.id,
            user_id=primer.accountant.id,
            family_id=uuid.uuid4(),
            digest=opaque_token_digest(new_opaque_token()),
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )
    )
    await session.flush()

    response = await api.delete(f"/members/{primer.accountant.id}", headers=primer.as_owner())

    assert response.status_code == 204
    assert await role_of(session, primer, primer.accountant) is None
    live = select(func.count()).where(RefreshToken.revoked_at.is_(None))
    assert await session.scalar(live) == 0
    gone = await api.get("/members", headers=primer.as_accountant())
    assert gone.status_code == 401
    assert gone.json() == {"detail": "the account or its membership is no longer active"}
    assert await session.get(User, primer.accountant.id) is not None  # the account remains


async def test_a_deactivated_account_is_refused_at_once(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    await session.execute(update(User).where(User.id == primer.owner.id).values(is_active=False))

    response = await api.get("/members", headers=primer.as_owner())

    assert response.status_code == 401


@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
async def test_an_unknown_member_is_not_found(
    api: AsyncClient, primer: Office, method: str
) -> None:
    response = await api.request(
        method,
        f"/members/{uuid.uuid4()}",
        json={"role": "client"} if method == "PATCH" else None,
        headers=primer.as_owner(),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "no such member in this organization"}


async def test_a_member_of_several_organizations_keeps_the_others(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    other = Organization(name="Ogled")
    session.add(other)
    await session.flush()
    await join(session, other, primer.accountant, Role.ACCOUNTANT)

    await api.delete(f"/members/{primer.accountant.id}", headers=primer.as_owner())

    stays = await api.get("/members", headers=bearer(primer.accountant, other, Role.ACCOUNTANT))
    assert stays.status_code == 200


async def test_openapi_documents_the_members_endpoints_behind_the_access_token(
    client: AsyncClient,
) -> None:
    paths = (await client.get("/openapi.json")).json()["paths"]

    for path, method in (("/members", "get"), ("/members/{user_id}", "patch")):
        assert paths[path][method]["tags"] == ["members"]
        assert paths[path][method]["security"] == [{"access token": []}]
    assert set(paths["/members/{user_id}"]["delete"]["responses"]) == {"204", "404", "409", "422"}
