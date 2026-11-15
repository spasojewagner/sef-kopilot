"""An organization's own key to a model may be to Google's Gemini (ADR-0066).

The model keys' list of providers gains `gemini`. Undoing the revision forgets the keys to
Gemini, since the list no longer has a place for them: those organizations' explanations and
repairs go back to the operator's model.

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KNOWN = "ck_model_keys_provider_known"


def upgrade() -> None:
    op.drop_constraint(op.f(_KNOWN), "model_keys", type_="check")
    op.create_check_constraint(
        op.f(_KNOWN), "model_keys", "provider IN ('groq', 'openai', 'anthropic', 'gemini')"
    )


def downgrade() -> None:
    op.execute("DELETE FROM model_keys WHERE provider = 'gemini'")
    op.drop_constraint(op.f(_KNOWN), "model_keys", type_="check")
    op.create_check_constraint(
        op.f(_KNOWN), "model_keys", "provider IN ('groq', 'openai', 'anthropic')"
    )
