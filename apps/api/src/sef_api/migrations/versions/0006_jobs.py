"""Jobs: work done in the background for an organization, with its progress and its outcome.

A new table only; undoing the revision drops every job, finished or not.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UNFINISHED = sa.text("status IN ('queued', 'running')")


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("submitted_by", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'queued'"), nullable=False),
        sa.Column(
            "parameters",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "progress",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(status IN ('succeeded', 'failed')) = (finished_at IS NOT NULL)",
            name=op.f("ck_jobs_finished_when_done"),
        ),
        sa.CheckConstraint("kind IN ('revalidation')", name=op.f("ck_jobs_kind_known")),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name=op.f("ck_jobs_status_known"),
        ),
        sa.CheckConstraint(
            "version >= 0 AND attempts >= 0", name=op.f("ck_jobs_counts_not_negative")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_jobs_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by"],
            ["users.id"],
            name=op.f("fk_jobs_submitted_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    )
    op.create_index(
        "ix_jobs_organization_id_created_at_id", "jobs", ["organization_id", "created_at", "id"]
    )
    op.create_index(op.f("ix_jobs_submitted_by"), "jobs", ["submitted_by"])
    op.create_index(
        "uq_jobs_unfinished_per_member",
        "jobs",
        ["organization_id", "submitted_by", "kind"],
        unique=True,
        postgresql_where=UNFINISHED,
    )


def downgrade() -> None:
    op.drop_index("uq_jobs_unfinished_per_member", table_name="jobs", postgresql_where=UNFINISHED)
    op.drop_index(op.f("ix_jobs_submitted_by"), table_name="jobs")
    op.drop_index("ix_jobs_organization_id_created_at_id", table_name="jobs")
    op.drop_table("jobs")
