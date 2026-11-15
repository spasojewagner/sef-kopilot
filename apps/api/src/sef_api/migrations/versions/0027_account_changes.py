"""Record organization renames and keep a password version for web access tokens.

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KNOWN = "ck_audit_events_action_known"
_ACTIONS = (
    "'repair.proposed', 'repair.approved', 'repair.rejected', "
    "'organization.retention_set', 'oauth.client_authorized', 'sef.key_set', "
    "'sef.key_removed', 'sef.invoice_sent', 'model.key_set', 'model.key_removed'"
)


def upgrade() -> None:
    op.add_column("users", sa.Column("password_version", sa.Uuid(), nullable=True))
    op.drop_constraint(op.f(_KNOWN), "audit_events", type_="check")
    op.create_check_constraint(
        op.f(_KNOWN), "audit_events", f"action IN ({_ACTIONS}, 'organization.renamed')"
    )


def downgrade() -> None:
    op.execute("DELETE FROM audit_events WHERE action = 'organization.renamed'")
    op.drop_constraint(op.f(_KNOWN), "audit_events", type_="check")
    op.create_check_constraint(op.f(_KNOWN), "audit_events", f"action IN ({_ACTIONS})")
    op.drop_column("users", "password_version")
