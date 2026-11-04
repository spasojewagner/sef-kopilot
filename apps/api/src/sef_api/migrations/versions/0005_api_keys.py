"""API keys, each acting for a member of an organization.

A new table only; undoing the revision drops every key, and the machine clients that use them
can no longer authenticate.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("prefix", sa.Text(), nullable=False),
        sa.Column("digest", sa.Text(), nullable=False),
        sa.Column("permissions", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "permissions <@ "
            "ARRAY['invoices:validate', 'invoices:submit', 'invoices:manage']::text[]",
            name=op.f("ck_api_keys_permissions_known"),
        ),
        sa.CheckConstraint(
            "cardinality(permissions) > 0", name=op.f("ck_api_keys_has_permissions")
        ),
        sa.CheckConstraint(
            "char_length(btrim(name)) BETWEEN 1 AND 100", name=op.f("ck_api_keys_name_length")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["memberships.organization_id", "memberships.user_id"],
            name=op.f("fk_api_keys_organization_id_user_id_memberships"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_keys")),
        sa.UniqueConstraint("digest", name=op.f("uq_api_keys_digest")),
    )
    op.create_index(
        "ix_api_keys_organization_id_user_id", "api_keys", ["organization_id", "user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_api_keys_organization_id_user_id", table_name="api_keys")
    op.drop_table("api_keys")
