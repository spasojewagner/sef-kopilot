"""An organization's API key to SEF, sealed, and the audit of who set or removed it.

A new table, empty: an owner sets the organization's key once SEF_FERNET_KEY is set (ADR-0050).
The audit log learns the two actions that record it. Undoing the revision forgets every
organization's key, and the events that recorded who set or removed one, since the audit log's
list of actions no longer has a place for them.

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTIONS_BEFORE = (
    "action IN ('repair.proposed', 'repair.approved', 'repair.rejected', "
    "'organization.retention_set', 'oauth.client_authorized')"
)
ACTIONS = (
    "action IN ('repair.proposed', 'repair.approved', 'repair.rejected', "
    "'organization.retention_set', 'oauth.client_authorized', 'sef.key_set', "
    "'sef.key_removed')"
)


def upgrade() -> None:
    op.create_table(
        "sef_keys",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column(
            "set_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "token ~ '^gAAAAA[A-Za-z0-9_-]+={0,2}$'", name=op.f("ck_sef_keys_token_is_fernet")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_sef_keys_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("organization_id", name=op.f("pk_sef_keys")),
    )
    op.drop_constraint(op.f("ck_audit_events_action_known"), "audit_events", type_="check")
    op.create_check_constraint(op.f("ck_audit_events_action_known"), "audit_events", ACTIONS)


def downgrade() -> None:
    op.execute("DELETE FROM audit_events WHERE action IN ('sef.key_set', 'sef.key_removed')")
    op.drop_constraint(op.f("ck_audit_events_action_known"), "audit_events", type_="check")
    op.create_check_constraint(op.f("ck_audit_events_action_known"), "audit_events", ACTIONS_BEFORE)
    op.drop_table("sef_keys")
