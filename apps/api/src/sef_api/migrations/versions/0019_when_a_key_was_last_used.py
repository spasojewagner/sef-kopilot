"""When each API key was last used.

One column, empty for every key so far: a request with a key writes the time, at most once a
minute, so that a member sees which of their keys still serve a machine and which can go.
Undoing the revision forgets when the keys were used.

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("api_keys", sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("api_keys", "last_used_at")
