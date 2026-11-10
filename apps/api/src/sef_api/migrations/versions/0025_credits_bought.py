"""Credits an organization bought, through the provider of payments (ADR-0060): a kind of entry
of the ledger that names the payment, once.

The ledger's entries gain the provider's reference of a payment, which no two entries share, so
that a payment reported twice is counted once. Undoing the revision takes the purchases out of
the ledger and their credits out of the balances, down to zero at least: what was bought is
then forgotten, as the revision before knew nothing of it.

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS = "ck_credit_entries_kind_known"


def upgrade() -> None:
    op.add_column("credit_entries", sa.Column("reference", sa.Text(), nullable=True))
    op.create_unique_constraint(
        op.f("uq_credit_entries_reference"), "credit_entries", ["reference"]
    )
    op.drop_constraint(op.f(_KINDS), "credit_entries", type_="check")
    op.create_check_constraint(
        op.f(_KINDS), "credit_entries", "kind IN ('opening', 'spend', 'grant', 'purchase')"
    )
    op.create_check_constraint(
        op.f("ck_credit_entries_purchase_named"),
        "credit_entries",
        "(kind = 'purchase') = (reference IS NOT NULL)",
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE credit_accounts AS account
        SET balance = GREATEST(account.balance - bought.credits, 0)
        FROM (
            SELECT organization_id, sum(delta) AS credits
            FROM credit_entries WHERE kind = 'purchase' GROUP BY organization_id
        ) AS bought
        WHERE account.organization_id = bought.organization_id
        """
    )
    op.execute("DELETE FROM credit_entries WHERE kind = 'purchase'")
    op.drop_constraint(op.f("ck_credit_entries_purchase_named"), "credit_entries", type_="check")
    op.drop_constraint(op.f(_KINDS), "credit_entries", type_="check")
    op.create_check_constraint(
        op.f(_KINDS), "credit_entries", "kind IN ('opening', 'spend', 'grant')"
    )
    op.drop_constraint(op.f("uq_credit_entries_reference"), "credit_entries", type_="unique")
    op.drop_column("credit_entries", "reference")
