"""An index of each organization's invalid invoices, newest first.

After a revalidation an organization lists the invoices it found invalid, a few among many. A
partial index holds those alone, so the listing reads only them however many valid invoices the
organization keeps; it serves a query whose predicate is ``NOT valid``, as the listing's is.

The index is built ``CONCURRENTLY``, which does not hold writes back while it is built and
cannot run inside a transaction. A build that fails leaves the index behind marked invalid, so
the upgrade first drops whatever an earlier attempt left. Undoing the revision drops the index.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "ix_invoices_invalid_organization_id_created_at_id"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(INDEX, table_name="invoices", if_exists=True, postgresql_concurrently=True)
        op.create_index(
            INDEX,
            "invoices",
            ["organization_id", "created_at", "id"],
            postgresql_where=sa.text("NOT valid"),
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(INDEX, table_name="invoices", if_exists=True, postgresql_concurrently=True)
