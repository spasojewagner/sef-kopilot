"""The schema on PostgreSQL: keys, constraints and what goes with what."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import delete, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.auth.permissions import KEY_PERMISSIONS, Permission
from sef_api.models import (
    ApiKey,
    Invitation,
    Job,
    JobStatus,
    Membership,
    Organization,
    Role,
    StoredInvoice,
    User,
)


def person(email: str) -> User:
    """A user; the hash is a placeholder, these tests are about the schema, not passwords."""
    return User(email=email, password_hash="$argon2id$placeholder")


#: The listing columns that come together: an invoice's number, date and amount due.
LISTED = {"number": "RF-1", "issue_date": date(2026, 11, 4), "payable_amount": Decimal("1.00")}


def stored(
    organization: Organization, content: bytes = b"<Invoice/>", **columns: Any
) -> StoredInvoice:
    """An invoice as the schema sees it: a document, its digest and a report."""
    values: dict[str, Any] = {
        "organization_id": organization.id,
        "profile": "srb",
        "valid": False,
        "report": {"profile": "srb", "valid": False, "violations": [], "layers": []},
        "report_size": 64,
        "content": content,
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    return StoredInvoice(**(values | columns))


def key(membership: Membership, **columns: Any) -> ApiKey:
    """An API key as the schema sees it: a digest, a name and the permissions it holds."""
    values: dict[str, Any] = {
        "organization_id": membership.organization_id,
        "user_id": membership.user_id,
        "name": "ERP",
        "prefix": "sefk_0123456",
        "digest": secrets.token_hex(32),
        "permissions": ["invoices:validate"],
    }
    return ApiKey(**(values | columns))


async def member(session: AsyncSession, role: Role = Role.CLIENT) -> Membership:
    """A member of a new organization."""
    primer, ana = Organization(name="Primer"), person("ana@primer.example")
    session.add_all([primer, ana])
    await session.flush()
    membership = Membership(organization_id=primer.id, user_id=ana.id, role=role)
    session.add(membership)
    await session.flush()
    return membership


def invitation(organization: Organization, email: str, **columns: Any) -> Invitation:
    return Invitation(
        organization_id=organization.id,
        email=email,
        role=Role.CLIENT,
        digest=secrets.token_hex(32),
        expires_at=datetime.now(UTC) + timedelta(days=7),
        **columns,
    )


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
    session.add(person("ana@primer.example"))
    await session.flush()
    session.add(person("ana@primer.example"))

    with pytest.raises(IntegrityError, match="uq_users_email"):
        await session.flush()


async def test_an_email_address_is_stored_in_lower_case(session: AsyncSession) -> None:
    session.add(person("Ana@Primer.example"))

    with pytest.raises(IntegrityError, match="ck_users_email_lower_case"):
        await session.flush()


async def test_a_new_user_is_active(session: AsyncSession) -> None:
    user = person("nova@primer.example")
    session.add(user)
    await session.flush()

    assert user.is_active is True


async def test_a_member_has_one_of_three_roles(session: AsyncSession) -> None:
    organization, user = Organization(name="Primer"), person("ana@primer.example")
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
    user = person("ana@primer.example")
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
    organization, user = Organization(name="Primer"), person("ana@primer.example")
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
    organization, user = Organization(name="Primer"), person("ana@primer.example")
    session.add_all([organization, user])
    await session.flush()
    session.add(Membership(organization_id=organization.id, user_id=user.id, role=Role.OWNER))
    await session.flush()

    gone = organization.id if removed is Organization else user.id
    await session.execute(delete(removed).where(removed.id == gone))

    assert await session.scalar(select(func.count()).select_from(Membership)) == 0


async def test_an_address_has_one_open_invitation_per_organization(session: AsyncSession) -> None:
    primer, ogled = Organization(name="Primer"), Organization(name="Ogled")
    session.add_all([primer, ogled])
    await session.flush()
    session.add_all(
        [
            invitation(primer, "nova@primer.example", revoked_at=datetime.now(UTC)),
            invitation(primer, "nova@primer.example", accepted_at=datetime.now(UTC)),
            invitation(primer, "nova@primer.example"),
            invitation(ogled, "nova@primer.example"),
        ]
    )
    await session.flush()  # closed invitations and other organizations do not count
    session.add(invitation(primer, "nova@primer.example"))

    with pytest.raises(IntegrityError, match="uq_invitations_organization_id_email_open"):
        await session.flush()


async def test_an_invited_address_is_stored_in_lower_case(session: AsyncSession) -> None:
    primer = Organization(name="Primer")
    session.add(primer)
    await session.flush()
    session.add(invitation(primer, "Nova@Primer.example"))

    with pytest.raises(IntegrityError, match="ck_invitations_email_lower_case"):
        await session.flush()


async def test_an_invitation_goes_with_its_organization_and_forgets_a_deleted_inviter(
    session: AsyncSession,
) -> None:
    primer, inviter = Organization(name="Primer"), person("ana@primer.example")
    session.add_all([primer, inviter])
    await session.flush()
    session.add(invitation(primer, "nova@primer.example", invited_by=inviter.id))
    await session.flush()

    await session.execute(delete(User).where(User.id == inviter.id))
    assert await session.scalar(select(Invitation.invited_by)) is None

    await session.execute(delete(Organization).where(Organization.id == primer.id))
    assert await session.scalar(select(func.count()).select_from(Invitation)) == 0


async def test_an_invoice_is_kept_byte_for_byte_and_its_document_loaded_only_when_asked(
    session: AsyncSession,
) -> None:
    primer = Organization(name="Primer")
    session.add(primer)
    await session.flush()
    document = b"\xef\xbb\xbf<Invoice>\r\n  <cbc:Note>Ra\xc4\x8dun</cbc:Note>\r\n</Invoice>"
    session.add(stored(primer, document))
    await session.flush()
    session.expunge_all()

    listed = await session.scalar(select(StoredInvoice))
    assert listed is not None
    assert "content" in inspect(listed).unloaded
    assert listed.created_at.tzinfo is not None
    assert await session.scalar(select(StoredInvoice.content)) == document


@pytest.mark.parametrize(
    ("columns", "constraint"),
    [
        ({"size": 3}, "ck_invoices_size_of_content"),
        ({"sha256": "A" * 64}, "ck_invoices_sha256_hex"),
        ({"profile": "xrechnung"}, "ck_invoices_profile_known"),
        ({"document_type": "Order", **LISTED}, "ck_invoices_document_type_known"),
        ({"document_type": "Invoice"}, "ck_invoices_listed_together"),
        ({"report_size": 0}, "ck_invoices_report_size_positive"),
    ],
)
async def test_an_invoice_is_what_its_columns_say(
    session: AsyncSession, columns: dict[str, Any], constraint: str
) -> None:
    primer = Organization(name="Primer")
    session.add(primer)
    await session.flush()
    session.add(stored(primer, **columns))

    with pytest.raises(IntegrityError, match=constraint):
        await session.flush()


async def test_an_invoice_goes_with_its_organization_and_forgets_a_deleted_submitter(
    session: AsyncSession,
) -> None:
    primer, submitter = Organization(name="Primer"), person("ana@primer.example")
    session.add_all([primer, submitter])
    await session.flush()
    session.add(stored(primer, submitted_by=submitter.id))
    await session.flush()

    await session.execute(delete(User).where(User.id == submitter.id))
    assert await session.scalar(select(StoredInvoice.submitted_by)) is None

    await session.execute(delete(Organization).where(Organization.id == primer.id))
    assert await session.scalar(select(func.count()).select_from(StoredInvoice)) == 0


async def test_an_api_key_belongs_to_a_member_of_its_organization(session: AsyncSession) -> None:
    membership = await member(session)
    ogled = Organization(name="Ogled")
    session.add(ogled)
    await session.flush()
    session.add(key(membership, organization_id=ogled.id))

    with pytest.raises(IntegrityError, match="fk_api_keys_organization_id_user_id_memberships"):
        await session.flush()


async def test_an_api_key_goes_with_its_membership(session: AsyncSession) -> None:
    membership = await member(session)
    session.add_all([key(membership), key(membership)])
    await session.flush()

    await session.execute(
        delete(Membership).where(
            Membership.organization_id == membership.organization_id,
            Membership.user_id == membership.user_id,
        )
    )

    assert await session.scalar(select(func.count()).select_from(ApiKey)) == 0


@pytest.mark.parametrize("deleted", ["organization", "user"])
async def test_an_api_key_goes_with_its_organization_or_its_user(
    session: AsyncSession, deleted: str
) -> None:
    membership = await member(session)
    session.add(key(membership))
    await session.flush()

    if deleted == "organization":
        await session.execute(
            delete(Organization).where(Organization.id == membership.organization_id)
        )
    else:
        await session.execute(delete(User).where(User.id == membership.user_id))

    assert await session.scalar(select(func.count()).select_from(ApiKey)) == 0


async def test_a_digest_belongs_to_one_api_key(session: AsyncSession) -> None:
    membership = await member(session)
    session.add_all([key(membership, digest="d" * 64), key(membership, digest="d" * 64)])

    with pytest.raises(IntegrityError, match="uq_api_keys_digest"):
        await session.flush()


@pytest.mark.parametrize(
    ("columns", "constraint"),
    [
        ({"name": "   "}, "ck_api_keys_name_length"),
        ({"name": "x" * 101}, "ck_api_keys_name_length"),
        ({"permissions": []}, "ck_api_keys_has_permissions"),
        ({"permissions": ["invoices:validate", "members:manage"]}, "ck_api_keys_permissions_known"),
    ],
)
async def test_an_api_key_is_what_its_columns_say(
    session: AsyncSession, columns: dict[str, Any], constraint: str
) -> None:
    session.add(key(await member(session), **columns))

    with pytest.raises(IntegrityError, match=constraint):
        await session.flush()


@pytest.mark.parametrize("permission", list(Permission))
async def test_an_api_key_may_hold_what_keys_may_hold_and_nothing_else(
    session: AsyncSession, permission: Permission
) -> None:
    session.add(key(await member(session), permissions=[permission.value]))

    if permission in KEY_PERMISSIONS:
        await session.flush()
    else:
        with pytest.raises(IntegrityError, match="ck_api_keys_permissions_known"):
            await session.flush()


async def test_a_new_api_key_has_a_creation_time_and_neither_an_expiry_nor_a_revocation(
    session: AsyncSession,
) -> None:
    created = key(await member(session), name="x" * 100)  # the longest name there may be
    session.add(created)
    await session.flush()
    await session.refresh(created)

    assert created.created_at.tzinfo is not None
    assert (created.expires_at, created.revoked_at) == (None, None)


def job(membership: Membership, **columns: Any) -> Job:
    """A job as the schema sees it: a kind, for a member of an organization."""
    values: dict[str, Any] = {
        "organization_id": membership.organization_id,
        "submitted_by": membership.user_id,
        "kind": "revalidation",
    }
    return Job(**(values | columns))


async def test_a_new_job_waits_with_nothing_done_and_nothing_tried(session: AsyncSession) -> None:
    queued = job(await member(session))
    session.add(queued)
    await session.flush()

    assert (queued.status, queued.version, queued.attempts) == ("queued", 0, 0)
    assert (queued.parameters, queued.progress, queued.result, queued.error) == ({}, {}, None, None)
    assert queued.created_at.tzinfo is not None
    assert (queued.started_at, queued.finished_at) == (None, None)


async def test_a_member_has_one_unfinished_job_of_a_kind(session: AsyncSession) -> None:
    membership = await member(session)
    session.add(job(membership, status="running"))
    await session.flush()
    session.add(job(membership))

    with pytest.raises(IntegrityError, match="uq_jobs_unfinished_per_member"):
        await session.flush()


async def test_finished_jobs_and_other_members_do_not_count_against_the_one(
    session: AsyncSession,
) -> None:
    membership = await member(session)
    colleague = person("ivan@primer.example")
    session.add(colleague)
    await session.flush()
    session.add(
        Membership(
            organization_id=membership.organization_id, user_id=colleague.id, role=Role.CLIENT
        )
    )
    session.add_all(
        [
            job(membership, status="succeeded", finished_at=func.now()),
            job(membership, status="failed", finished_at=func.now()),
            job(membership),
            job(membership, submitted_by=colleague.id),
            job(membership, submitted_by=None),
            job(membership, submitted_by=None),
        ]
    )

    await session.flush()

    assert await session.scalar(select(func.count()).select_from(Job)) == 6


@pytest.mark.parametrize(
    ("columns", "constraint"),
    [
        ({"kind": "explanation"}, "ck_jobs_kind_known"),
        ({"status": "cancelled"}, "ck_jobs_status_known"),
        ({"status": "succeeded"}, "ck_jobs_finished_when_done"),
        ({"status": "running", "finished_at": func.now()}, "ck_jobs_finished_when_done"),
        ({"version": -1}, "ck_jobs_counts_not_negative"),
        ({"attempts": -1}, "ck_jobs_counts_not_negative"),
    ],
)
async def test_a_job_is_what_its_columns_say(
    session: AsyncSession, columns: dict[str, Any], constraint: str
) -> None:
    session.add(job(await member(session), **columns))

    with pytest.raises(IntegrityError, match=constraint):
        await session.flush()


async def test_a_job_goes_with_its_organization_and_forgets_a_deleted_submitter(
    session: AsyncSession,
) -> None:
    membership = await member(session)
    kept = job(membership)
    session.add(kept)
    await session.flush()

    await session.execute(delete(User).where(User.id == membership.user_id))
    await session.refresh(kept)
    submitter = kept.submitted_by
    await session.execute(delete(Organization).where(Organization.id == membership.organization_id))

    assert submitter is None
    assert await session.scalar(select(func.count()).select_from(Job)) == 0


def test_the_statuses_of_a_job() -> None:
    assert [status.value for status in JobStatus] == ["queued", "running", "succeeded", "failed"]
