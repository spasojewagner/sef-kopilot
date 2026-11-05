"""When each stored invoice was last validated: a column on the invoices.

An invoice stored before this revision was last validated when it was stored, so the column is
filled from ``created_at`` before it becomes required. Undoing the revision drops the column.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("invoices", sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE invoices SET validated_at = created_at")
    op.alter_column("invoices", "validated_at", nullable=False, server_default=sa.text("now()"))


def downgrade() -> None:
    op.drop_column("invoices", "validated_at")
