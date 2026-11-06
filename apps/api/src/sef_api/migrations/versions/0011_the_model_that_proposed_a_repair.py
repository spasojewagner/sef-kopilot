"""The language model that wrote a repair's patches, when one did.

A new column that may be empty, so every repair proposed so far keeps its meaning: a member or
a machine client wrote its patches. Undoing the revision forgets which repairs a model wrote.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("repairs", sa.Column("model", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("repairs", "model")
