"""The tenancy schema: organizations, the people who use the product, their memberships, the
invitations that create memberships, sign-in sessions, and the invoices an organization keeps.

An organization is the tenant: every table that holds a tenant's data carries an
``organization_id`` (ADR-0011). People are global — one e-mail address, one account — and
belong to organizations through memberships, each with one role; an invitation lets a person
join in a role (ADR-0013). A refresh token belongs to a person's session in one organization
(ADR-0012). A stored invoice belongs to an organization, and remembers who submitted it
(ADR-0016). An API key belongs to a membership, and acts for that member (ADR-0017). A job is
work done in the background for an organization, such as validating its invoices again
(ADR-0019).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    Numeric,
    Text,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from sef_api.db import Base

__all__ = [
    "UNFINISHED",
    "ApiKey",
    "Invitation",
    "Job",
    "JobKind",
    "JobStatus",
    "Membership",
    "Organization",
    "RefreshToken",
    "Role",
    "StoredInvoice",
    "User",
]


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


class StoredInvoice(Base):
    """An invoice an organization keeps: the document as it was sent, and the validator's report
    on it when it was stored.

    The columns from ``document_type`` on are what the validator read from the document, for
    listing it; they are empty when it could not be read as an invoice, and the number, date
    and amount due are there together or not at all. ``size`` and ``report_size`` are the bytes
    of the document and of the report, which the organization's storage quota counts.
    ``content`` is loaded only when it is asked for.
    """

    __tablename__ = "invoices"
    #: The time of a new invoice, set by the database, comes back with its insert.
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012
    __table_args__ = (
        CheckConstraint("size = octet_length(content)", name="size_of_content"),
        CheckConstraint("report_size > 0", name="report_size_positive"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_hex"),
        CheckConstraint("profile IN ('srb', 'en16931', 'peppol')", name="profile_known"),
        CheckConstraint("document_type IN ('Invoice', 'CreditNote')", name="document_type_known"),
        CheckConstraint(
            "num_nulls(document_type, number, issue_date, payable_amount) IN (0, 4)",
            name="listed_together",
        ),
        Index("ix_invoices_organization_id_created_at_id", "organization_id", "created_at", "id"),
    )

    id: Mapped[uuid.UUID] = _id()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = _created_at()
    profile: Mapped[str] = mapped_column(Text)
    valid: Mapped[bool]
    report: Mapped[dict[str, Any]] = mapped_column(JSONB)
    report_size: Mapped[int]
    content: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    size: Mapped[int]
    sha256: Mapped[str] = mapped_column(Text)
    document_type: Mapped[str | None] = mapped_column(Text)
    number: Mapped[str | None] = mapped_column(Text)
    issue_date: Mapped[date | None]
    currency: Mapped[str | None] = mapped_column(Text)
    seller: Mapped[str | None] = mapped_column(Text)
    buyer: Mapped[str | None] = mapped_column(Text)
    payable_amount: Mapped[Decimal | None] = mapped_column(Numeric)


class ApiKey(Base):
    """A key a machine client authenticates with, acting for the member who issued it with some
    of their permissions.

    The key is shown once, when it is issued; the table keeps its SHA-256 digest, and in
    ``prefix`` its first characters, by which people tell their keys apart. A key belongs to a
    membership: it is deleted with it, so that a person who is removed and invited back does
    not find their old keys working again. It works until it is revoked or it expires.
    """

    __tablename__ = "api_keys"
    #: The time of a new key, set by the database, comes back with its insert.
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["memberships.organization_id", "memberships.user_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("char_length(btrim(name)) BETWEEN 1 AND 100", name="name_length"),
        CheckConstraint("cardinality(permissions) > 0", name="has_permissions"),
        CheckConstraint(
            "permissions <@ "
            "ARRAY['invoices:validate', 'invoices:submit', 'invoices:manage']::text[]",
            name="permissions_known",
        ),
        Index("ix_api_keys_organization_id_user_id", "organization_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = _id()
    organization_id: Mapped[uuid.UUID]
    user_id: Mapped[uuid.UUID]
    name: Mapped[str] = mapped_column(Text)
    prefix: Mapped[str] = mapped_column(Text)
    digest: Mapped[str] = mapped_column(Text, unique=True)
    permissions: Mapped[list[str]] = mapped_column(ARRAY(Text))
    created_at: Mapped[datetime] = _created_at()
    expires_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]


class JobKind(StrEnum):
    """What a job does."""

    REVALIDATION = "revalidation"
    """Validates an organization's stored invoices again, against the rule sets of today."""


class JobStatus(StrEnum):
    """Where a job is: waiting for a worker, being worked on, or finished one way or the other."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


#: The statuses of a job that has not finished.
UNFINISHED: tuple[JobStatus, ...] = (JobStatus.QUEUED, JobStatus.RUNNING)


class Job(Base):
    """Work done in the background for an organization: what, for whom, how far it has come,
    and how it ended.

    The row is the job's truth; a queue only carries the news that it is waiting. ``version``
    grows with every change, so that a reader can tell what it has seen already. ``attempts``
    counts the times a worker took the job on; the latest attempt is the one whose writes
    count, so that a worker that was given up for dead cannot overwrite its successor. A member
    has at most one unfinished job of each kind.
    """

    __tablename__ = "jobs"
    #: The defaults the database sets come back with the insert.
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012
    __table_args__ = (
        CheckConstraint("kind IN ('revalidation')", name="kind_known"),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')", name="status_known"
        ),
        CheckConstraint(
            "(status IN ('succeeded', 'failed')) = (finished_at IS NOT NULL)",
            name="finished_when_done",
        ),
        CheckConstraint("version >= 0 AND attempts >= 0", name="counts_not_negative"),
        Index("ix_jobs_organization_id_created_at_id", "organization_id", "created_at", "id"),
        Index(
            "uq_jobs_unfinished_per_member",
            "organization_id",
            "submitted_by",
            "kind",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )

    id: Mapped[uuid.UUID] = _id()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    #: The member who started the job; forgotten if their account is deleted.
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'queued'"))
    #: What the job works on, as the kind defines it.
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    #: How far the job has come, as the kind defines it.
    progress: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    #: What the job came to, once it has succeeded.
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    #: Why the job failed: a short message, never the content of an invoice.
    error: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(server_default=text("0"))
    attempts: Mapped[int] = mapped_column(server_default=text("0"))
    created_at: Mapped[datetime] = _created_at()
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
