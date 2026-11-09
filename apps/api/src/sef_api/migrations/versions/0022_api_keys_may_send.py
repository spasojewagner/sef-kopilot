"""API keys may send invoices to SEF.

The permissions a key may hold gain ``invoices:send``, for an ERP that sends its organization's
invoices to SEF with a key of an owner or an accountant. Undoing the revision takes the
permission from every key that holds it, and revokes a key that held nothing else, since the
earlier schema has no permission for it to keep.

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-09
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The constraint's name as it stands in the database, the naming convention applied.
_KNOWN = "ck_api_keys_permissions_known"
_BEFORE = "'invoices:validate', 'invoices:submit', 'invoices:manage'"


def upgrade() -> None:
    op.drop_constraint(op.f(_KNOWN), "api_keys", type_="check")
    op.create_check_constraint(
        op.f(_KNOWN), "api_keys", f"permissions <@ ARRAY[{_BEFORE}, 'invoices:send']::text[]"
    )


def downgrade() -> None:
    # A key that could only send keeps a permission the earlier schema knows, and stops working.
    op.execute(
        "UPDATE api_keys SET revoked_at = coalesce(revoked_at, now()), "
        "permissions = ARRAY['invoices:validate'] "
        "WHERE permissions = ARRAY['invoices:send']"
    )
    op.execute(
        "UPDATE api_keys SET permissions = array_remove(permissions, 'invoices:send') "
        "WHERE 'invoices:send' = ANY(permissions)"
    )
    op.drop_constraint(op.f(_KNOWN), "api_keys", type_="check")
    op.create_check_constraint(op.f(_KNOWN), "api_keys", f"permissions <@ ARRAY[{_BEFORE}]::text[]")
