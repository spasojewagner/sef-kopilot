"""Invitations to join an organization.

A new table only; undoing the revision drops the invitations that are still open, and the
codes handed out for them stop working.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OPEN = sa.text("accepted_at IS NULL AND revoked_at IS NULL")


def upgrade() -> None:
    op.create_table(
        "invitations",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "owner",
                "accountant",
                "client",
                name="role",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("digest", sa.Text(), nullable=False),
        sa.Column("invited_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("email = lower(email)", name=op.f("ck_invitations_email_lower_case")),
        sa.ForeignKeyConstraint(
            ["invited_by"],
            ["users.id"],
            name=op.f("fk_invitations_invited_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_invitations_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invitations")),
        sa.UniqueConstraint("digest", name=op.f("uq_invitations_digest")),
    )
    op.create_index(op.f("ix_invitations_invited_by"), "invitations", ["invited_by"])
    op.create_index(op.f("ix_invitations_organization_id"), "invitations", ["organization_id"])
    op.create_index(
        "uq_invitations_organization_id_email_open",
        "invitations",
        ["organization_id", "email"],
        unique=True,
        postgresql_where=OPEN,
    )


def downgrade() -> None:
    op.drop_index("uq_invitations_organization_id_email_open", table_name="invitations")
    op.drop_index(op.f("ix_invitations_organization_id"), table_name="invitations")
    op.drop_index(op.f("ix_invitations_invited_by"), table_name="invitations")
    op.drop_table("invitations")
