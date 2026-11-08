"""The MCP client a member acted through, in the audit log.

One column, empty for every event so far: an act done through an MCP client, under the
member's consent, names the client as an act done with an API key names the key (ADR-0044).
Undoing the revision forgets which client an act came through.

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("audit_events", sa.Column("oauth_client_id", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("audit_events", "oauth_client_id")
