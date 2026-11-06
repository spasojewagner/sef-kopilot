"""Repairs of stored invoices, and the audit log of who proposed and decided them.

New tables only; undoing the revision drops every repair, decided or not, and every audit
event.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("actor", sa.Uuid(), nullable=False),
        sa.Column("key_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=True),
        sa.Column("repair_id", sa.Uuid(), nullable=True),
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('repair.proposed', 'repair.approved', 'repair.rejected')",
            name=op.f("ck_audit_events_action_known"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_audit_events_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(
        "ix_audit_events_organization_id_at_id",
        "audit_events",
        ["organization_id", "at", "id"],
        unique=False,
    )
    op.create_table(
        "repairs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("proposed_by", sa.Uuid(), nullable=True),
        sa.Column("key_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), server_default=sa.text("'proposed'"), nullable=False),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("based_on", sa.Text(), nullable=False),
        sa.Column("patched_sha256", sa.Text(), nullable=False),
        sa.Column("outcomes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("changed", sa.Boolean(), nullable=False),
        sa.Column("valid", sa.Boolean(), nullable=False),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("diff", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "(status = 'proposed') = (decided_at IS NULL)",
            name=op.f("ck_repairs_decided_unless_proposed"),
        ),
        sa.CheckConstraint(
            "based_on ~ '^[0-9a-f]{64}$' AND patched_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_repairs_digests_hex"),
        ),
        sa.CheckConstraint(
            "status IN ('proposed', 'approved', 'rejected', 'superseded')",
            name=op.f("ck_repairs_status_known"),
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"],
            ["users.id"],
            name=op.f("fk_repairs_decided_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["invoices.id"],
            name=op.f("fk_repairs_invoice_id_invoices"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["key_id"],
            ["api_keys.id"],
            name=op.f("fk_repairs_key_id_api_keys"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_repairs_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["proposed_by"],
            ["users.id"],
            name=op.f("fk_repairs_proposed_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_repairs")),
    )
    op.create_index(op.f("ix_repairs_decided_by"), "repairs", ["decided_by"], unique=False)
    op.create_index(
        "ix_repairs_invoice_id_created_at_id",
        "repairs",
        ["invoice_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(op.f("ix_repairs_key_id"), "repairs", ["key_id"], unique=False)
    op.create_index(
        op.f("ix_repairs_organization_id"), "repairs", ["organization_id"], unique=False
    )
    op.create_index(op.f("ix_repairs_proposed_by"), "repairs", ["proposed_by"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_repairs_proposed_by"), table_name="repairs")
    op.drop_index(op.f("ix_repairs_organization_id"), table_name="repairs")
    op.drop_index(op.f("ix_repairs_key_id"), table_name="repairs")
    op.drop_index("ix_repairs_invoice_id_created_at_id", table_name="repairs")
    op.drop_index(op.f("ix_repairs_decided_by"), table_name="repairs")
    op.drop_table("repairs")
    op.drop_index("ix_audit_events_organization_id_at_id", table_name="audit_events")
    op.drop_table("audit_events")
