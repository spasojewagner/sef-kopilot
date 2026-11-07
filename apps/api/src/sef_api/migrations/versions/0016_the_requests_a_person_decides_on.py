"""The requests of OAuth clients, which a person decides on, and the codes their consent issues.

A new table, empty: a row is a client's request to act for a person, the person's decision and
the code it issues (ADR-0044). It goes with the client and with the member who approved it. The
audit log learns the action of a consent. Undoing the revision forgets every request and every
code, and the audit log's records of consents, since its list of actions then has no place for
them.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTIONS_BEFORE = (
    "action IN ('repair.proposed', 'repair.approved', 'repair.rejected', "
    "'organization.retention_set')"
)
ACTIONS = (
    "action IN ('repair.proposed', 'repair.approved', 'repair.rejected', "
    "'organization.retention_set', 'oauth.client_authorized')"
)


def upgrade() -> None:
    op.create_table(
        "oauth_authorizations",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("client_id", sa.Text(), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("code_challenge", sa.Text(), nullable=False),
        sa.Column("scopes", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("code_sha256", sa.Text(), nullable=True),
        sa.Column("code_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "decision IN ('approved', 'refused')",
            name=op.f("ck_oauth_authorizations_decision_known"),
        ),
        sa.CheckConstraint(
            "(decision = 'approved') = (organization_id IS NOT NULL AND user_id IS NOT NULL "
            "AND code_sha256 IS NOT NULL AND code_expires_at IS NOT NULL)",
            name=op.f("ck_oauth_authorizations_approved_with_a_member_and_a_code"),
        ),
        sa.CheckConstraint(
            "(decision IS NULL) = (decided_at IS NULL)",
            name=op.f("ck_oauth_authorizations_decided_when"),
        ),
        sa.CheckConstraint(
            "code_sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_oauth_authorizations_code_sha256_hex")
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["oauth_clients.id"],
            name=op.f("fk_oauth_authorizations_client_id_oauth_clients"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["memberships.organization_id", "memberships.user_id"],
            name=op.f("fk_oauth_authorizations_organization_id_memberships"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_authorizations")),
        sa.UniqueConstraint("code_sha256", name=op.f("uq_oauth_authorizations_code_sha256")),
    )
    op.create_index(
        op.f("ix_oauth_authorizations_client_id"),
        "oauth_authorizations",
        ["client_id"],
        unique=False,
    )
    op.create_index(
        "ix_oauth_authorizations_organization_id_user_id",
        "oauth_authorizations",
        ["organization_id", "user_id"],
        unique=False,
    )
    op.drop_constraint(op.f("ck_audit_events_action_known"), "audit_events", type_="check")
    op.create_check_constraint(op.f("ck_audit_events_action_known"), "audit_events", ACTIONS)


def downgrade() -> None:
    op.execute("DELETE FROM audit_events WHERE action = 'oauth.client_authorized'")
    op.drop_constraint(op.f("ck_audit_events_action_known"), "audit_events", type_="check")
    op.create_check_constraint(op.f("ck_audit_events_action_known"), "audit_events", ACTIONS_BEFORE)
    op.drop_index("ix_oauth_authorizations_organization_id_user_id", "oauth_authorizations")
    op.drop_index(op.f("ix_oauth_authorizations_client_id"), "oauth_authorizations")
    op.drop_table("oauth_authorizations")
