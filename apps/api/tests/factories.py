"""People, organizations, memberships, stored invoices, API keys, jobs and SEF keys made
directly in the database, with access tokens for the people, for tests about what happens after
sign-in."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from einvoice_core.pipeline import ValidationReport
from sef_api.api_keys.service import PREFIX, SHOWN
from sef_api.auth.permissions import KEY_PERMISSIONS, Permission
from sef_api.auth.tokens import issue_access_token, new_opaque_token, opaque_token_digest
from sef_api.models import (
    ApiKey,
    Job,
    JobKind,
    Membership,
    Organization,
    Role,
    SefKey,
    StoredInvoice,
    User,
)
from sef_api.sef.keys import Keyring

from .conftest import TEST_FERNET_KEY, TEST_JWT_SECRET

#: Seals and opens SEF keys as the test applications do.
KEYRING = Keyring((TEST_FERNET_KEY,))

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


async def stored_invoice(
    session: AsyncSession,
    organization: Organization,
    submitted_by: User | None,
    content: bytes = b"<Invoice/>",
    **columns: Any,
) -> StoredInvoice:
    """An invoice ``organization`` stores, with an empty report on it unless ``columns`` say
    otherwise: what reading it shows, not what the validator would say."""
    report = ValidationReport(profile="srb", valid=False, violations=(), layers=())
    stored = {
        "profile": "srb",
        "valid": False,
        "report": report.model_dump(mode="json"),
        "report_size": len(report.model_dump_json()),
    }
    invoice = StoredInvoice(
        organization_id=organization.id,
        submitted_by=None if submitted_by is None else submitted_by.id,
        content=content,
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        **(stored | columns),
    )
    session.add(invoice)
    await session.flush()
    return invoice


@dataclass(frozen=True)
class Key:
    """An API key's row, and the key itself."""

    row: ApiKey
    secret: str

    def header(self) -> dict[str, str]:
        """The header with which a machine client sends the key."""
        return {"Authorization": f"Bearer {self.secret}"}


async def api_key(
    session: AsyncSession,
    organization: Organization,
    user: User,
    *permissions: Permission,
    **columns: Any,
) -> Key:
    """A key that acts for ``user`` in ``organization`` with ``permissions``, every permission
    a key may hold when none is named."""
    secret = PREFIX + new_opaque_token()
    row = ApiKey(
        organization_id=organization.id,
        user_id=user.id,
        name="ERP",
        prefix=secret[:SHOWN],
        digest=opaque_token_digest(secret),
        permissions=sorted(permission.value for permission in permissions or KEY_PERMISSIONS),
        **columns,
    )
    session.add(row)
    await session.flush()
    return Key(row, secret)


async def job(
    session: AsyncSession, organization: Organization, user: User | None, **columns: Any
) -> Job:
    """A job of ``organization`` started by ``user``: a revalidation that waits, unless told
    otherwise."""
    queued = Job(
        organization_id=organization.id,
        submitted_by=user.id if user is not None else None,
        kind=JobKind.REVALIDATION,
        **columns,
    )
    session.add(queued)
    await session.flush()
    return queued


async def sef_key(session: AsyncSession, organization: Organization, api_key: str) -> SefKey:
    """``api_key`` as ``organization``'s key to SEF, sealed as the test applications seal it."""
    sealed = SefKey(
        organization_id=organization.id, token=KEYRING.seal(organization.id, SecretStr(api_key))
    )
    session.add(sealed)
    await session.flush()
    return sealed
