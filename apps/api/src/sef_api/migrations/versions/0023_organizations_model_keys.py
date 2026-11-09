"""An organization's own key to a language model's provider, sealed, and the audit of who set or
removed it (ADR-0058).

A new table, empty: an owner sets the organization's key, its provider and, if not its default,
its model, once SEF_FERNET_KEY is set. The audit log learns the two actions that record it.
Undoing the revision forgets every organization's key to a model, and the events that recorded
who set or removed one, since the audit log's list of actions no longer has a place for them;
the organizations' explanations and repairs go back to the operator's model.

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The constraint's name as it stands in the database, the naming convention applied.
_KNOWN = "ck_audit_events_action_known"
ACTIONS_BEFORE = (
    "action IN ('repair.proposed', 'repair.approved', 'repair.rejected', "
    "'organization.retention_set', 'oauth.client_authorized', 'sef.key_set', "
    "'sef.key_removed', 'sef.invoice_sent')"
)
ACTIONS = (
    "action IN ('repair.proposed', 'repair.approved', 'repair.rejected', "
    "'organization.retention_set', 'oauth.client_authorized', 'sef.key_set', "
    "'sef.key_removed', 'sef.invoice_sent', 'model.key_set', 'model.key_removed')"
)


def upgrade() -> None:
    op.create_table(
        "model_keys",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column(
            "set_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "token ~ '^gAAAAA[A-Za-z0-9_-]+={0,2}$'", name=op.f("ck_model_keys_token_is_fernet")
        ),
        sa.CheckConstraint(
            "provider IN ('groq', 'openai', 'anthropic')",
            name=op.f("ck_model_keys_provider_known"),
        ),
        sa.CheckConstraint(
            "model IS NULL OR model ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$'",
            name=op.f("ck_model_keys_model_named"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_model_keys_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("organization_id", name=op.f("pk_model_keys")),
    )
    op.drop_constraint(op.f(_KNOWN), "audit_events", type_="check")
    op.create_check_constraint(op.f(_KNOWN), "audit_events", ACTIONS)


def downgrade() -> None:
    op.execute("DELETE FROM audit_events WHERE action IN ('model.key_set', 'model.key_removed')")
    op.drop_constraint(op.f(_KNOWN), "audit_events", type_="check")
    op.create_check_constraint(op.f(_KNOWN), "audit_events", ACTIONS_BEFORE)
    op.drop_table("model_keys")
