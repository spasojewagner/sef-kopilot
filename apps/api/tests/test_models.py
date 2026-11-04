"""The tenancy schema on PostgreSQL: keys, constraints and what goes with what."""

from __future__ import annotations

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.models import Membership, Organization, Role, User


async def test_an_organization_gets_an_id_and_a_timezone_aware_creation_time(
    session: AsyncSession,
) -> None:
    organization = Organization(name="Primer Računovodstvo")
    session.add(organization)
    await session.flush()
    await session.refresh(organization)

    assert organization.id is not None
    assert organization.created_at.tzinfo is not None


@pytest.mark.parametrize("name", ["", "   ", "x" * 201])
async def test_an_organization_name_has_1_to_200_characters(
    session: AsyncSession, name: str
) -> None:
    session.add(Organization(name=name))

    with pytest.raises(IntegrityError, match="ck_organizations_name_length"):
        await session.flush()


async def test_an_email_address_belongs_to_one_user(session: AsyncSession) -> None:
    session.add(User(email="ana@primer.example"))
    await session.flush()
    session.add(User(email="ana@primer.example"))

    with pytest.raises(IntegrityError, match="uq_users_email"):
        await session.flush()


async def test_an_email_address_is_stored_in_lower_case(session: AsyncSession) -> None:
    session.add(User(email="Ana@Primer.example"))

    with pytest.raises(IntegrityError, match="ck_users_email_lower_case"):
        await session.flush()


async def test_a_new_user_is_active(session: AsyncSession) -> None:
    user = User(email="nova@primer.example")
    session.add(user)
    await session.flush()

    assert user.is_active is True


async def test_a_member_has_one_of_three_roles(session: AsyncSession) -> None:
    organization, user = Organization(name="Primer"), User(email="ana@primer.example")
    session.add_all([organization, user])
    await session.flush()

    with pytest.raises(IntegrityError, match="ck_memberships_role"):
        await session.execute(
            text(
                "INSERT INTO memberships (organization_id, user_id, role) "
                "VALUES (:organization, :user, 'admin')"
            ),
            {"organization": organization.id, "user": user.id},
        )


async def test_a_user_can_be_a_member_of_several_organizations(session: AsyncSession) -> None:
    office, company = Organization(name="Knjigovodstvo Primer"), Organization(name="Ogledni Kupac")
    user = User(email="ana@primer.example")
    session.add_all([office, company, user])
    await session.flush()
    session.add_all(
        [
            Membership(organization_id=office.id, user_id=user.id, role=Role.ACCOUNTANT),
            Membership(organization_id=company.id, user_id=user.id, role=Role.CLIENT),
        ]
    )
    await session.flush()

    roles = await session.scalars(
        select(Membership.role).where(Membership.user_id == user.id).order_by(Membership.role)
    )
    assert list(roles) == [Role.ACCOUNTANT, Role.CLIENT]


async def test_a_user_is_a_member_of_an_organization_once(session: AsyncSession) -> None:
    organization, user = Organization(name="Primer"), User(email="ana@primer.example")
    session.add_all([organization, user])
    await session.flush()
    session.add(Membership(organization_id=organization.id, user_id=user.id, role=Role.OWNER))
    await session.flush()
    session.expunge_all()
    session.add(Membership(organization_id=organization.id, user_id=user.id, role=Role.CLIENT))

    with pytest.raises(IntegrityError, match="pk_memberships"):
        await session.flush()


@pytest.mark.parametrize("removed", [Organization, User])
async def test_memberships_are_removed_with_their_organization_or_user(
    session: AsyncSession, removed: type[Organization] | type[User]
) -> None:
    organization, user = Organization(name="Primer"), User(email="ana@primer.example")
    session.add_all([organization, user])
    await session.flush()
    session.add(Membership(organization_id=organization.id, user_id=user.id, role=Role.OWNER))
    await session.flush()

    gone = organization.id if removed is Organization else user.id
    await session.execute(delete(removed).where(removed.id == gone))

    assert await session.scalar(select(func.count()).select_from(Membership)) == 0
