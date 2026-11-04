"""People, organizations and memberships made directly in the database, with access tokens for
them, for tests about what happens after sign-in."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.auth.tokens import issue_access_token
from sef_api.models import Membership, Organization, Role, User

from .conftest import TEST_JWT_SECRET

#: In the form of an argon2id hash but the hash of no password: these people never sign in.
NO_PASSWORD = "$argon2id$v=19$m=19456,t=2,p=1$c2FsdHNhbHQ$bm90IGEgaGFzaCBvZiBhbnl0aGluZw"


async def person(session: AsyncSession, email: str) -> User:
    user = User(email=email, password_hash=NO_PASSWORD)
    session.add(user)
    await session.flush()
    return user


async def organization(session: AsyncSession, name: str) -> Organization:
    created = Organization(name=name)
    session.add(created)
    await session.flush()
    return created


async def join(
    session: AsyncSession, organization: Organization, user: User, role: Role
) -> Membership:
    membership = Membership(organization_id=organization.id, user_id=user.id, role=role)
    session.add(membership)
    await session.flush()
    return membership


def bearer(user: User, organization: Organization, role: Role) -> dict[str, str]:
    """The header of an access token for ``user`` in ``organization`` with ``role``."""
    token, _ = issue_access_token(
        user.id, organization.id, role, secret=TEST_JWT_SECRET, lifetime=timedelta(minutes=15)
    )
    return {"Authorization": f"Bearer {token}"}


@dataclass(frozen=True)
class Office:
    """An accounting office with one member per role."""

    organization: Organization
    owner: User
    accountant: User
    client: User

    def as_owner(self) -> dict[str, str]:
        return bearer(self.owner, self.organization, Role.OWNER)

    def as_accountant(self) -> dict[str, str]:
        return bearer(self.accountant, self.organization, Role.ACCOUNTANT)

    def as_client(self) -> dict[str, str]:
        return bearer(self.client, self.organization, Role.CLIENT)


async def office(session: AsyncSession, name: str, domain: str) -> Office:
    """An organization ``name`` whose owner, accountant and client have addresses at ``domain``."""
    created = await organization(session, name)
    people: dict[Role, User] = {}
    for role in (Role.OWNER, Role.ACCOUNTANT, Role.CLIENT):
        people[role] = await person(session, f"{role.value}@{domain}")
        await join(session, created, people[role], role)
    return Office(created, people[Role.OWNER], people[Role.ACCOUNTANT], people[Role.CLIENT])
