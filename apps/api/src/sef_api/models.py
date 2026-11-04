"""The tenancy schema: organizations, the people who use the product, and their memberships.

An organization is the tenant: every table that holds a tenant's data carries an
``organization_id`` (ADR-0011). People are global — one e-mail address, one account — and
belong to organizations through memberships, each with one role.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Text, func, text, true
from sqlalchemy.orm import Mapped, mapped_column

from sef_api.db import Base

__all__ = ["Membership", "Organization", "Role", "User"]


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
    """A person who signs in; the e-mail address is stored in lower case and is unique."""

    __tablename__ = "users"
    __table_args__ = (CheckConstraint("email = lower(email)", name="email_lower_case"),)

    id: Mapped[uuid.UUID] = _id()
    email: Mapped[str] = mapped_column(Text, unique=True)
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
    role: Mapped[Role] = mapped_column(
        Enum(
            Role,
            name="role",
            native_enum=False,
            create_constraint=True,
            length=16,
            values_callable=lambda roles: [role.value for role in roles],
        )
    )
    created_at: Mapped[datetime] = _created_at()
