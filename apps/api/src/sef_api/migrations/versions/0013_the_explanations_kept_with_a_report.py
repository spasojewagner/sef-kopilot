"""The explanations of a stored invoice's report, kept with the invoice, one set a language.

A new table, empty: explanations written before it were not kept. Each row names the digest of
the report it explains, and goes with its invoice (ADR-0040). Undoing the revision forgets every
kept explanation, which the next request writes again.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "explanations",
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("report_sha256", sa.Text(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("explanations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("unexplained", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "written_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("language IN ('sr', 'en')", name=op.f("ck_explanations_language_known")),
        sa.CheckConstraint(
            "report_sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_explanations_report_sha256_hex")
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["invoices.id"],
            name=op.f("fk_explanations_invoice_id_invoices"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_explanations_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("invoice_id", "language", name=op.f("pk_explanations")),
    )
    op.create_index(
        op.f("ix_explanations_organization_id"), "explanations", ["organization_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_explanations_organization_id"), table_name="explanations")
    op.drop_table("explanations")
