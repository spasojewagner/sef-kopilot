"""The organizations' credits, where billing is on, and the ledger of every change of them
(ADR-0059).

Two new tables, empty: an organization's account is opened the first time it spends a credit,
with the credits the settings start it with. Undoing the revision forgets every organization's
credits and their history; storing invoices then costs nothing, as with billing off.

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "credit_accounts",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("balance", sa.Integer(), nullable=False),
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("balance >= 0", name=op.f("ck_credit_accounts_balance_not_negative")),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_credit_accounts_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("organization_id", name=op.f("pk_credit_accounts")),
    )
    op.create_table(
        "credit_entries",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("number", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('opening', 'spend', 'grant')", name=op.f("ck_credit_entries_kind_known")
        ),
        sa.CheckConstraint(
            "(kind = 'spend' AND delta < 0 AND invoice_id IS NOT NULL) "
            "OR (kind <> 'spend' AND delta > 0 AND invoice_id IS NULL)",
            name=op.f("ck_credit_entries_delta_follows_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_credit_entries_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credit_entries")),
        sa.UniqueConstraint("number", name=op.f("uq_credit_entries_number")),
    )
    op.create_index(
        "ix_credit_entries_organization_id_number",
        "credit_entries",
        ["organization_id", "number"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_credit_entries_organization_id_number", table_name="credit_entries")
    op.drop_table("credit_entries")
    op.drop_table("credit_accounts")
