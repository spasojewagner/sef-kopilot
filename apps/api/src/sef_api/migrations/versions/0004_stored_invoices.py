"""Invoices an organization keeps, with the validator's report on each.

A new table only; undoing the revision drops every stored invoice and its report.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "invoices",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("submitted_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("profile", sa.Text(), nullable=False),
        sa.Column("valid", sa.Boolean(), nullable=False),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("report_size", sa.Integer(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("document_type", sa.Text(), nullable=True),
        sa.Column("number", sa.Text(), nullable=True),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("currency", sa.Text(), nullable=True),
        sa.Column("seller", sa.Text(), nullable=True),
        sa.Column("buyer", sa.Text(), nullable=True),
        sa.Column("payable_amount", sa.Numeric(), nullable=True),
        sa.CheckConstraint(
            "document_type IN ('Invoice', 'CreditNote')",
            name=op.f("ck_invoices_document_type_known"),
        ),
        sa.CheckConstraint(
            "num_nulls(document_type, number, issue_date, payable_amount) IN (0, 4)",
            name=op.f("ck_invoices_listed_together"),
        ),
        sa.CheckConstraint(
            "profile IN ('srb', 'en16931', 'peppol')", name=op.f("ck_invoices_profile_known")
        ),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_invoices_sha256_hex")),
        sa.CheckConstraint("report_size > 0", name=op.f("ck_invoices_report_size_positive")),
        sa.CheckConstraint(
            "size = octet_length(content)", name=op.f("ck_invoices_size_of_content")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_invoices_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by"],
            ["users.id"],
            name=op.f("fk_invoices_submitted_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoices")),
    )
    op.create_index(
        "ix_invoices_organization_id_created_at_id",
        "invoices",
        ["organization_id", "created_at", "id"],
    )
    op.create_index(op.f("ix_invoices_submitted_by"), "invoices", ["submitted_by"])


def downgrade() -> None:
    op.drop_index(op.f("ix_invoices_submitted_by"), table_name="invoices")
    op.drop_index("ix_invoices_organization_id_created_at_id", table_name="invoices")
    op.drop_table("invoices")
