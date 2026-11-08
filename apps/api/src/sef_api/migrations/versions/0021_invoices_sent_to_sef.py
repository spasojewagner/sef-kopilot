"""The stored invoices sent to SEF, with what SEF answered, and the audit of who sent them.

A new table, empty: a member sends a stored invoice that the validator passes (ADR-0051). An
invoice has at most one submission that is unconfirmed or imported, and its submissions are
deleted with it. The audit log learns the action that records a sending. Undoing the revision
forgets what was sent and what SEF answered, and the events that recorded who sent what, since
the audit log's list of actions no longer has a place for them; SEF keeps the invoices.

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTIONS_BEFORE = (
    "action IN ('repair.proposed', 'repair.approved', 'repair.rejected', "
    "'organization.retention_set', 'oauth.client_authorized', 'sef.key_set', "
    "'sef.key_removed')"
)
ACTIONS = (
    "action IN ('repair.proposed', 'repair.approved', 'repair.rejected', "
    "'organization.retention_set', 'oauth.client_authorized', 'sef.key_set', "
    "'sef.key_removed', 'sef.invoice_sent')"
)
SEF_STATUSES = (
    "sef_status IN ('New', 'Draft', 'Sending', 'Sent', 'Mistake', 'Approved', 'Rejected', "
    "'Cancelled', 'Storno', 'Paid', 'OverDue', 'Archived', 'Deleted', 'Unknown')"
)


def upgrade() -> None:
    op.create_table(
        "sef_submissions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("submitted_by", sa.Uuid(), nullable=True),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("sales_invoice_id", sa.BigInteger(), nullable=True),
        sa.Column("sef_invoice_id", sa.BigInteger(), nullable=True),
        sa.Column("sef_status", sa.Text(), nullable=True),
        sa.Column("refusal", sa.Text(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "sent_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('unconfirmed', 'imported', 'refused')",
            name=op.f("ck_sef_submissions_state_known"),
        ),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_sef_submissions_sha256_hex")),
        sa.CheckConstraint(
            "(state = 'imported') = (sales_invoice_id IS NOT NULL)",
            name=op.f("ck_sef_submissions_imported_with_its_id"),
        ),
        sa.CheckConstraint(
            "(state = 'refused') = (refusal IS NOT NULL)",
            name=op.f("ck_sef_submissions_refused_with_a_reason"),
        ),
        sa.CheckConstraint(
            "refusal IN ('invoice', 'key')", name=op.f("ck_sef_submissions_refusal_known")
        ),
        sa.CheckConstraint(SEF_STATUSES, name=op.f("ck_sef_submissions_sef_status_known")),
        sa.CheckConstraint(
            "sef_status IS NULL OR state = 'imported'",
            name=op.f("ck_sef_submissions_status_once_imported"),
        ),
        sa.CheckConstraint("attempts >= 1", name=op.f("ck_sef_submissions_attempts_positive")),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["invoices.id"],
            name=op.f("fk_sef_submissions_invoice_id_invoices"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_sef_submissions_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by"],
            ["users.id"],
            name=op.f("fk_sef_submissions_submitted_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sef_submissions")),
    )
    op.create_index(
        op.f("ix_sef_submissions_invoice_id"), "sef_submissions", ["invoice_id"], unique=False
    )
    op.create_index(
        op.f("ix_sef_submissions_organization_id"),
        "sef_submissions",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "uq_sef_submissions_invoice_id_live",
        "sef_submissions",
        ["invoice_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('unconfirmed', 'imported')"),
    )
    op.drop_constraint(op.f("ck_audit_events_action_known"), "audit_events", type_="check")
    op.create_check_constraint(op.f("ck_audit_events_action_known"), "audit_events", ACTIONS)


def downgrade() -> None:
    op.execute("DELETE FROM audit_events WHERE action = 'sef.invoice_sent'")
    op.drop_constraint(op.f("ck_audit_events_action_known"), "audit_events", type_="check")
    op.create_check_constraint(op.f("ck_audit_events_action_known"), "audit_events", ACTIONS_BEFORE)
    op.drop_index("uq_sef_submissions_invoice_id_live", "sef_submissions")
    op.drop_index(op.f("ix_sef_submissions_organization_id"), "sef_submissions")
    op.drop_index(op.f("ix_sef_submissions_invoice_id"), "sef_submissions")
    op.drop_table("sef_submissions")
