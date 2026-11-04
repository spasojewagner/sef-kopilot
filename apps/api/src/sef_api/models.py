"""The tenancy schema: organizations, the people who use the product, their memberships, the
invitations that create memberships, and sign-in sessions.

An organization is the tenant: every table that holds a tenant's data carries an
``organization_id`` (ADR-0011). People are global — one e-mail address, one account — and
belong to organizations through memberships, each with one role; an invitation lets a person
join in a role (ADR-0013). A refresh token belongs to a person's session in one organization
(ADR-0012).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Text, func, text, true
from sqlalchemy.orm import Mapped, mapped_column

from sef_api.db import Base

__all__ = ["Invitation", "Membership", "Organization", "RefreshToken", "Role", "User"]


class Role(StrEnum):
    """What a member may do in an organization (the permissions follow from it)."""

    OWNER = "owner"
    """Runs the organization: members, API keys, billing, and everything an accountant does."""
    ACCOUNTANT = "accountant"
    """Works on invoices: validates, explains, repairs, approves and sends them."""
    CLIENT = "client"
    """Submits invoices and reads the results."""


def _id() -> Mapped[uuid.UUID]:
    return mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )


def _created_at() -> Mapped[datetime]:
    return mapped_column(server_default=func.now())


def _role() -> Enum:
    """A role column: VARCHAR with a CHECK on the values, which is simpler to migrate than a
    native PostgreSQL enumeration."""
    return Enum(
        Role,
        name="role",
        native_enum=False,
        create_constraint=True,
        length=16,
        values_callable=lambda roles: [role.value for role in roles],
    )


class Organization(Base):
    """A tenant: an accounting office, a company, an ERP vendor's customer."""

    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint("char_length(btrim(name)) BETWEEN 1 AND 200", name="name_length"),
    )

    id: Mapped[uuid.UUID] = _id()
    name: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


class User(Base):
    """A person who signs in; the e-mail address is stored in lower case and is unique.

    ``password_hash`` is an argon2id hash in PHC format, never the password.
    """

    __tablename__ = "users"
    __table_args__ = (CheckConstraint("email = lower(email)", name="email_lower_case"),)

    id: Mapped[uuid.UUID] = _id()
    email: Mapped[str] = mapped_column(Text, unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())
    created_at: Mapped[datetime] = _created_at()


class Membership(Base):
    """A user's role in an organization; removed with either of them."""

    __tablename__ = "memberships"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[Role] = mapped_column(_role())
    created_at: Mapped[datetime] = _created_at()


class Invitation(Base):
    """An invitation to join an organization in a role, redeemed once with its code.

    The code is shown once to the owner who creates the invitation, who passes it on; the table
    keeps its SHA-256 digest. An address has at most one open invitation per organization
    (``uq_invitations_organization_id_email_open``); an accepted or revoked one is closed.
    """

    __tablename__ = "invitations"
    __table_args__ = (
        CheckConstraint("email = lower(email)", name="email_lower_case"),
        Index(
            "uq_invitations_organization_id_email_open",
            "organization_id",
            "email",
            unique=True,
            postgresql_where=text("accepted_at IS NULL AND revoked_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = _id()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(Text)
    role: Mapped[Role] = mapped_column(_role())
    digest: Mapped[str] = mapped_column(Text, unique=True)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = _created_at()
    expires_at: Mapped[datetime]
    accepted_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]


class RefreshToken(Base):
    """One refresh token of a sign-in session, stored as the SHA-256 digest of the token.

    The tokens of one session share a ``family_id``: each is spent once (``used_at``) and
    replaced by the next. Presenting a spent or revoked token again means it was stolen or
    replayed, and revokes the whole family.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = _id()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    family_id: Mapped[uuid.UUID] = mapped_column(index=True)
    digest: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = _created_at()
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
