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

from sef_api.models import Invitation, Membership, Organization, Role, StoredInvoice, User


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
