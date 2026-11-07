"""The tokens a consent issues to an MCP client: when its code was exchanged, when the consent was
revoked, and its refresh tokens.

Two columns of the consents, empty, and a new table, empty: a refresh token is kept as its
SHA-256, spent once and replaced, and goes with its consent (ADR-0044). Undoing the revision
forgets every refresh token and when each code was exchanged: a client signs in again.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "oauth_authorizations",
        sa.Column("exchanged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "oauth_authorizations",
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_oauth_authorizations_exchanged_when_approved"),
        "oauth_authorizations",
        "exchanged_at IS NULL OR decision = 'approved'",
    )
    op.create_check_constraint(
        op.f("ck_oauth_authorizations_revoked_when_approved"),
        "oauth_authorizations",
        "revoked_at IS NULL OR decision = 'approved'",
    )
    op.create_table(
        "oauth_refresh_tokens",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("authorization_id", sa.Text(), nullable=False),
        sa.Column("digest", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_oauth_refresh_tokens_digest_hex")
        ),
        sa.ForeignKeyConstraint(
            ["authorization_id"],
            ["oauth_authorizations.id"],
            name=op.f("fk_oauth_refresh_tokens_authorization_id_oauth_authorizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_refresh_tokens")),
        sa.UniqueConstraint("digest", name=op.f("uq_oauth_refresh_tokens_digest")),
    )
    op.create_index(
        op.f("ix_oauth_refresh_tokens_authorization_id"),
        "oauth_refresh_tokens",
        ["authorization_id"],
        unique=False,
    )
    op.create_index(
        "uq_oauth_refresh_tokens_unspent",
        "oauth_refresh_tokens",
        ["authorization_id"],
        unique=True,
        postgresql_where=sa.text("used_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_oauth_refresh_tokens_unspent", "oauth_refresh_tokens")
    op.drop_index(op.f("ix_oauth_refresh_tokens_authorization_id"), "oauth_refresh_tokens")
    op.drop_table("oauth_refresh_tokens")
    op.drop_constraint(
        op.f("ck_oauth_authorizations_revoked_when_approved"), "oauth_authorizations", "check"
    )
    op.drop_constraint(
        op.f("ck_oauth_authorizations_exchanged_when_approved"), "oauth_authorizations", "check"
    )
    op.drop_column("oauth_authorizations", "revoked_at")
    op.drop_column("oauth_authorizations", "exchanged_at")
