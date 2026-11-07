"""How long an organization keeps its stored invoices, and the audit of who set it.

A new column that may be empty, so every organization keeps its invoices as before, until they
are deleted, until an owner sets a period of its own (ADR-0039). The audit log learns the action
that records it. Undoing the revision forgets every organization's period, and the events that
recorded who set one, since the audit log's list of actions no longer has a place for them.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTIONS_BEFORE = "action IN ('repair.proposed', 'repair.approved', 'repair.rejected')"
ACTIONS = (
    "action IN ('repair.proposed', 'repair.approved', 'repair.rejected', "
    "'organization.retention_set')"
)


def upgrade() -> None:
    op.add_column("organizations", sa.Column("invoice_retention_days", sa.Integer(), nullable=True))
    op.create_check_constraint(
        op.f("ck_organizations_invoice_retention_days_range"),
        "organizations",
        "invoice_retention_days BETWEEN 1 AND 3650",
    )
    op.drop_constraint(op.f("ck_audit_events_action_known"), "audit_events", type_="check")
    op.create_check_constraint(op.f("ck_audit_events_action_known"), "audit_events", ACTIONS)


def downgrade() -> None:
    op.execute("DELETE FROM audit_events WHERE action = 'organization.retention_set'")
    op.drop_constraint(op.f("ck_audit_events_action_known"), "audit_events", type_="check")
    op.create_check_constraint(op.f("ck_audit_events_action_known"), "audit_events", ACTIONS_BEFORE)
    op.drop_constraint(
        op.f("ck_organizations_invoice_retention_days_range"), "organizations", type_="check"
    )
    op.drop_column("organizations", "invoice_retention_days")
