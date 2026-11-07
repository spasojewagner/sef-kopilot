"""The clients of the OAuth 2.1 authorization server, which register themselves.

A new table, empty: an MCP client registers when it first connects (RFC 7591, ADR-0044). Its
rows belong to no organization. Undoing the revision forgets every client, which registers
again.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "oauth_clients",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("redirect_uris", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("grant_types", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "cardinality(redirect_uris) BETWEEN 1 AND 10",
            name=op.f("ck_oauth_clients_redirect_uris_count"),
        ),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 100", name=op.f("ck_oauth_clients_name_length")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_clients")),
    )


def downgrade() -> None:
    op.drop_table("oauth_clients")
