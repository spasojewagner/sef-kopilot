"""The corpus: the official documents an explanation cites, and their passages over time.

Adds the ``vector`` (pgvector) and ``pg_trgm`` extensions, which need a role that may create
them (a superuser locally, Neon's default role in production). Undoing the revision drops the
two tables and leaves the extensions, which hold no data and which other objects may use; the
corpus is rebuilt from ``corpus/`` by ``python -m sef_api.rag.ingest``.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import UserDefinedType

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


class _Vector(UserDefinedType[list[float]]):
    """pgvector's column type as this revision creates it: 1024 numbers."""

    cache_ok = True

    def get_col_spec(self, **kwargs: object) -> str:
        del kwargs
        return "vector(1024)"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "corpus_documents",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("publisher", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("page", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('law', 'rulebook', 'specification', 'list')",
            name=op.f("ck_corpus_documents_kind_known"),
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_corpus_documents")),
    )
    op.create_table(
        "corpus_passages",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("document", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("heading", sa.Text(), nullable=True),
        sa.Column("part", sa.Text(), nullable=True),
        sa.Column("amended_by", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("fully_from", sa.Date(), nullable=True),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("text_sha256", sa.Text(), nullable=False),
        sa.Column("embedding", _Vector(), nullable=True),
        sa.Column("embedding_model", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "(embedding IS NULL) = (embedding_model IS NULL)",
            name=op.f("ck_corpus_passages_embedding_with_its_model"),
        ),
        sa.CheckConstraint(
            "fully_from IS NULL OR fully_from > valid_from",
            name=op.f("ck_corpus_passages_fully_from_after_valid_from"),
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name=op.f("ck_corpus_passages_valid_to_after_valid_from"),
        ),
        sa.ForeignKeyConstraint(
            ["document"],
            ["corpus_documents.key"],
            name=op.f("fk_corpus_passages_document_corpus_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_corpus_passages")),
    )
    op.create_index(
        "uq_corpus_passages_document_key_valid_from",
        "corpus_passages",
        ["document", "key", "valid_from"],
        unique=True,
    )
    op.create_index(
        "ix_corpus_passages_embedding",
        "corpus_passages",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_corpus_passages_search_text",
        "corpus_passages",
        ["search_text"],
        postgresql_using="gin",
        postgresql_ops={"search_text": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_corpus_passages_search_text", table_name="corpus_passages")
    op.drop_index("ix_corpus_passages_embedding", table_name="corpus_passages")
    op.drop_index("uq_corpus_passages_document_key_valid_from", table_name="corpus_passages")
    op.drop_table("corpus_passages")
    op.drop_table("corpus_documents")
