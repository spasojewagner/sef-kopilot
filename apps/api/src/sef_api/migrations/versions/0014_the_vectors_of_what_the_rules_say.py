"""The vectors of what the rules say, kept once an embedding model.

A new table, empty: each text is embedded the next time an explanation needs it, and kept
(ADR-0041). Its rows are public text's vectors and belong to no organization. Undoing the
revision forgets them, and the embedder is asked again.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.types import UserDefinedType

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


class _Vector(UserDefinedType[list[float]]):
    """pgvector's column type as this revision creates it: 1024 numbers."""

    cache_ok = True

    def get_col_spec(self, **kwargs: object) -> str:
        del kwargs
        return "vector(1024)"


def upgrade() -> None:
    op.create_table(
        "rule_embeddings",
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("text_sha256", sa.Text(), nullable=False),
        sa.Column("embedding", _Vector(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "text_sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_rule_embeddings_text_sha256_hex")
        ),
        sa.PrimaryKeyConstraint("model", "text_sha256", name=op.f("pk_rule_embeddings")),
    )


def downgrade() -> None:
    op.drop_table("rule_embeddings")
