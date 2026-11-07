"""The tenancy schema: organizations, the people who use the product, their memberships, the
invitations that create memberships, sign-in sessions, and the invoices an organization keeps.

An organization is the tenant: every table that holds a tenant's data carries an
``organization_id`` (ADR-0011). People are global — one e-mail address, one account — and
belong to organizations through memberships, each with one role; an invitation lets a person
join in a role (ADR-0013). A refresh token belongs to a person's session in one organization
(ADR-0012). A stored invoice belongs to an organization, and remembers who submitted it
(ADR-0016). An API key belongs to a membership, and acts for that member (ADR-0017). A job is
work done in the background for an organization, such as validating its invoices again
(ADR-0019). A repair is patches proposed for a stored invoice, kept with what they did to it until
a person decides, and the audit log records who proposed and decided what (ADR-0024). The
explanations of a stored invoice's report are kept with it, one set a language (ADR-0040).

The corpus, the official documents an explanation cites, is the same for every organization
and belongs to none (ADR-0020): its passages are public text, written only by the command that
ingests the corpus. So do the vectors of what the rules say, kept once a model (ADR-0041).
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

from sef_api.db import Base, Vector
from sef_api.rag.embeddings import DIMENSIONS

__all__ = [
    "UNFINISHED",
    "ApiKey",
    "AuditAction",
    "AuditEvent",
    "CorpusDocument",
    "CorpusPassage",
    "Invitation",
    "Job",
    "JobKind",
    "JobStatus",
    "Membership",
    "Organization",
    "RefreshToken",
    "Repair",
    "RepairStatus",
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
    """A tenant: an accounting office, a company, an ERP vendor's customer.

    ``invoice_retention_days`` is how long, after it was stored, the organization keeps an
    invoice before it is deleted; none keeps every invoice until it is deleted (ADR-0039).
    """

    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint("char_length(btrim(name)) BETWEEN 1 AND 200", name="name_length"),
        CheckConstraint(
            "invoice_retention_days BETWEEN 1 AND 3650", name="invoice_retention_days_range"
        ),
    )

    id: Mapped[uuid.UUID] = _id()
    name: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()
    invoice_retention_days: Mapped[int | None]


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
    """An invoice an organization keeps: the document as it was sent, and the validator's latest
    report on it.

    The report and the columns from ``document_type`` on are what the validator said and read
    when it last validated the document (``validated_at``): when it was stored, or when it was
    validated again (ADR-0019). The columns from ``document_type`` on are what it read, for
    listing it; they are empty when it could not be read as an invoice, and the number, date
    and amount due are there together or not at all. ``size`` and ``report_size`` are the bytes
    of the document and of the report, which the organization's storage quota counts.
    ``content`` is loaded only when it is asked for.
    """

    __tablename__ = "invoices"
    #: The times of a new invoice, set by the database, come back with its insert.
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
        # The invalid invoices, the few an organization looks for after a revalidation: their
        # own index, as small as they are few (migration 0009).
        Index(
            "ix_invoices_invalid_organization_id_created_at_id",
            "organization_id",
            "created_at",
            "id",
            postgresql_where=text("NOT valid"),
        ),
    )

    id: Mapped[uuid.UUID] = _id()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = _created_at()
    #: When the validator last judged the document, which is when it was stored until it is
    #: validated again.
    validated_at: Mapped[datetime] = mapped_column(server_default=func.now())
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


class RepairStatus(StrEnum):
    """Where a repair is: waiting for a person, or decided."""

    PROPOSED = "proposed"
    """Its patches were applied to a copy of the invoice; the invoice is as it was."""
    APPROVED = "approved"
    """A person approved it, and the invoice became the document its patches left."""
    REJECTED = "rejected"
    """A person rejected it; the invoice is as it was."""
    SUPERSEDED = "superseded"
    """The invoice changed before anyone decided, so its patches no longer apply to the
    document they were proposed for."""


class Repair(Base):
    """Patches proposed for one stored invoice, with what they did to a copy of it, until a
    person decides (ADR-0024).

    The patches were applied to the document whose digest is ``based_on``; each patch is in
    ``outcomes``, with what became of it. ``changed``, ``valid``, ``report`` and ``diff`` are
    what they did, and ``patched_sha256`` is the digest of the document they left. The invoice
    does not change until a person approves the repair. A repair belongs to its invoice and is
    deleted with it; the audit log keeps that it was proposed and decided. ``model`` names the
    language model that wrote the patches, when one did (ADR-0025).
    """

    __tablename__ = "repairs"
    #: The defaults the database sets come back with the insert.
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012
    __table_args__ = (
        CheckConstraint(
            "status IN ('proposed', 'approved', 'rejected', 'superseded')", name="status_known"
        ),
        CheckConstraint(
            "(status = 'proposed') = (decided_at IS NULL)", name="decided_unless_proposed"
        ),
        CheckConstraint(
            "based_on ~ '^[0-9a-f]{64}$' AND patched_sha256 ~ '^[0-9a-f]{64}$'",
            name="digests_hex",
        ),
        Index("ix_repairs_invoice_id_created_at_id", "invoice_id", "created_at", "id"),
    )

    id: Mapped[uuid.UUID] = _id()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"))
    #: The member who proposed it, in person or through an API key; forgotten if their account
    #: is deleted.
    proposed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    #: The API key it was proposed with; None when the member proposed it in person, or once
    #: the key is deleted.
    key_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("api_keys.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = _created_at()
    status: Mapped[str] = mapped_column(Text, server_default=text("'proposed'"))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    decided_at: Mapped[datetime | None]
    based_on: Mapped[str] = mapped_column(Text)
    patched_sha256: Mapped[str] = mapped_column(Text)
    outcomes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    changed: Mapped[bool]
    valid: Mapped[bool]
    report: Mapped[dict[str, Any]] = mapped_column(JSONB)
    diff: Mapped[str] = mapped_column(Text)
    #: The language model that wrote the patches, which ``proposed_by`` asked it for; None for
    #: the patches a member or a machine client wrote.
    model: Mapped[str | None] = mapped_column(Text)


class OAuthClient(Base):
    """A client of the OAuth 2.1 authorization server that registered itself (RFC 7591, ADR-0044):
    an assistant, say, that will ask a person to let it use the MCP server.

    Every client is public: it authenticates with no secret, and proves with PKCE that it is the
    one that began an authorization. Registering grants nothing; a person does, once the client
    asks. The row belongs to no organization, since a client is not anyone's until a person lets
    it act for them.
    """

    __tablename__ = "oauth_clients"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012
    __table_args__ = (
        CheckConstraint("cardinality(redirect_uris) BETWEEN 1 AND 10", name="redirect_uris_count"),
        CheckConstraint("char_length(name) BETWEEN 1 AND 100", name="name_length"),
    )

    #: The ``client_id``, random, which the client sends with every request.
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str | None] = mapped_column(Text)
    #: Where an authorization may send the person back, compared exactly.
    redirect_uris: Mapped[list[str]] = mapped_column(ARRAY(Text))
    #: ``authorization_code``, and ``refresh_token`` if the client asked for it.
    grant_types: Mapped[list[str]] = mapped_column(ARRAY(Text))
    created_at: Mapped[datetime] = _created_at()


class OAuthAuthorization(Base):
    """A client's request to act for a person, from the moment it asks (``/oauth/authorize``) to
    the person's decision and the code it issues (ADR-0044).

    The request names what the client asked: where to send the person back, the PKCE challenge,
    the scopes, the resource and its state. Its id, random, is the address of the page where a
    person decides; it expires ten minutes after it was made. Approved, it holds the member who
    approved and, by its SHA-256, the code the client will exchange, which expires within two
    minutes; it goes with the membership, as an API key does.
    """

    __tablename__ = "oauth_authorizations"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["memberships.organization_id", "memberships.user_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("decision IN ('approved', 'refused')", name="decision_known"),
        CheckConstraint(
            "(decision = 'approved') = (organization_id IS NOT NULL AND user_id IS NOT NULL "
            "AND code_sha256 IS NOT NULL AND code_expires_at IS NOT NULL)",
            name="approved_with_a_member_and_a_code",
        ),
        CheckConstraint("(decision IS NULL) = (decided_at IS NULL)", name="decided_when"),
        CheckConstraint("code_sha256 ~ '^[0-9a-f]{64}$'", name="code_sha256_hex"),
        Index("ix_oauth_authorizations_organization_id_user_id", "organization_id", "user_id"),
    )

    #: The request's id: random, the address of the page where a person decides on it.
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    client_id: Mapped[str] = mapped_column(
        ForeignKey("oauth_clients.id", ondelete="CASCADE"), index=True
    )
    redirect_uri: Mapped[str] = mapped_column(Text)
    #: The PKCE challenge, S256: the SHA-256 of the client's verifier, base64url.
    code_challenge: Mapped[str] = mapped_column(Text)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text))
    #: The resource the token will be for (RFC 8707): the MCP endpoint.
    resource: Mapped[str] = mapped_column(Text)
    state: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()
    expires_at: Mapped[datetime]
    decision: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None]
    organization_id: Mapped[uuid.UUID | None]
    user_id: Mapped[uuid.UUID | None]
    code_sha256: Mapped[str | None] = mapped_column(Text, unique=True)
    code_expires_at: Mapped[datetime | None]


class RuleEmbedding(Base):
    """The vector of what a rule says, as one embedding model made it, kept so that each text is
    asked of the embedder once (ADR-0041).

    The text is public, the rule's own words (``meaning_text``), never an invoice's, so the row
    belongs to no organization, as the corpus does (ADR-0020). A vector is only compared with
    vectors of its model, so the model is half of its key; the other half is the text's digest.
    """

    __tablename__ = "rule_embeddings"
    #: The time the database sets comes back with the insert.
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012
    __table_args__ = (CheckConstraint("text_sha256 ~ '^[0-9a-f]{64}$'", name="text_sha256_hex"),)

    model: Mapped[str] = mapped_column(Text, primary_key=True)
    text_sha256: Mapped[str] = mapped_column(Text, primary_key=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(DIMENSIONS))
    created_at: Mapped[datetime] = _created_at()


class KeptExplanations(Base):
    """The explanations of a stored invoice's report in one language, written once and read by
    every member who may see the invoice (ADR-0040).

    ``report_sha256`` is the digest of the report they explain, and ``day`` the day whose law
    they cite: once the invoice's report is another, they explain a report it no longer has, and
    the next explanation replaces them. They hold what the rules' messages say, which may quote
    the invoice, so they are deleted with it.
    """

    __tablename__ = "explanations"
    #: The time the database sets comes back with the insert.
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012
    __table_args__ = (
        CheckConstraint("language IN ('sr', 'en')", name="language_known"),
        CheckConstraint("report_sha256 ~ '^[0-9a-f]{64}$'", name="report_sha256_hex"),
    )

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), primary_key=True
    )
    language: Mapped[str] = mapped_column(Text, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    report_sha256: Mapped[str] = mapped_column(Text)
    day: Mapped[date]
    model: Mapped[str] = mapped_column(Text)
    explanations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    unexplained: Mapped[list[str]] = mapped_column(JSONB)
    written_at: Mapped[datetime] = _created_at()


class AuditAction(StrEnum):
    """What an audit event records."""

    REPAIR_PROPOSED = "repair.proposed"
    REPAIR_APPROVED = "repair.approved"
    REPAIR_REJECTED = "repair.rejected"
    ORGANIZATION_RETENTION_SET = "organization.retention_set"
    OAUTH_CLIENT_AUTHORIZED = "oauth.client_authorized"


class AuditEvent(Base):
    """Something done in an organization that it must be able to account for: what, when, by
    which member and with which key, to which invoice and repair (ADR-0024).

    Events are only ever added. They name the member, the key, the invoice and the repair by
    id, without a foreign key, so that an event outlives what it names; and they hold no
    invoice content: digests, counts, and the places patches name with what became of them,
    never a value or a reason. They are deleted with the organization.
    """

    __tablename__ = "audit_events"
    #: The time of a new event, set by the database, comes back with its insert.
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012
    __table_args__ = (
        CheckConstraint(
            "action IN ('repair.proposed', 'repair.approved', 'repair.rejected', "
            "'organization.retention_set', 'oauth.client_authorized')",
            name="action_known",
        ),
        Index("ix_audit_events_organization_id_at_id", "organization_id", "at", "id"),
    )

    id: Mapped[uuid.UUID] = _id()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    at: Mapped[datetime] = _created_at()
    actor: Mapped[uuid.UUID]
    key_id: Mapped[uuid.UUID | None]
    action: Mapped[str] = mapped_column(Text)
    invoice_id: Mapped[uuid.UUID | None]
    repair_id: Mapped[uuid.UUID | None]
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))


class CorpusDocument(Base):
    """An official document of the corpus: a law, a rulebook, a specification or a list."""

    __tablename__ = "corpus_documents"
    __table_args__ = (
        CheckConstraint("kind IN ('law', 'rulebook', 'specification', 'list')", name="kind_known"),
    )

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    publisher: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(Text)
    #: Where the document is published.
    page: Mapped[str] = mapped_column(Text)


class CorpusPassage(Base):
    """A passage of an official document, with the days between which it applies.

    ``id`` names the document, the passage and the day it began to apply
    (``e-invoicing-law/article-4b/2027-07-01``): an explanation's citations are these ids.
    ``search_text`` is the passage folded for keyword search, ``text_sha256`` a digest of what
    it says, and ``embedding`` its vector, made by ``embedding_model``, or neither until the
    passage is embedded.
    """

    __tablename__ = "corpus_passages"
    __table_args__ = (
        CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from", name="valid_to_after_valid_from"
        ),
        CheckConstraint(
            "fully_from IS NULL OR fully_from > valid_from", name="fully_from_after_valid_from"
        ),
        CheckConstraint(
            "(embedding IS NULL) = (embedding_model IS NULL)", name="embedding_with_its_model"
        ),
        Index(
            "uq_corpus_passages_document_key_valid_from",
            "document",
            "key",
            "valid_from",
            unique=True,
        ),
        Index(
            "ix_corpus_passages_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index(
            "ix_corpus_passages_search_text",
            "search_text",
            postgresql_using="gin",
            postgresql_ops={"search_text": "gin_trgm_ops"},
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    document: Mapped[str] = mapped_column(ForeignKey("corpus_documents.key", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(Text)
    label: Mapped[str] = mapped_column(Text)
    heading: Mapped[str | None] = mapped_column(Text)
    part: Mapped[str | None] = mapped_column(Text)
    amended_by: Mapped[list[str]] = mapped_column(ARRAY(Text))
    valid_from: Mapped[date]
    valid_to: Mapped[date | None]
    fully_from: Mapped[date | None]
    version: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    search_text: Mapped[str] = mapped_column(Text)
    text_sha256: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(DIMENSIONS))
    embedding_model: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
