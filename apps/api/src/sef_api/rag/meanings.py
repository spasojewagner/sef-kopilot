"""The vectors of what the rules say, kept once an embedding model (ADR-0041).

An explanation finds passages by what each rule says (:func:`~sef_api.rag.retrieval.meaning_text`)
as well as by its words. Those texts are the rules' own and few, while invoices that fail the
same rules are many: each text is asked of the embedder once a model, and its vector kept. What
is kept is public text's vector, so it belongs to no organization, as the corpus does (ADR-0020).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.models import RuleEmbedding

__all__ = ["keep", "kept"]


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


async def kept(session: AsyncSession, model: str, texts: Iterable[str]) -> dict[str, list[float]]:
    """The vectors ``model`` made of ``texts`` and that are kept, by text; a text without one is
    left out."""
    by_digest = {_digest(text): text for text in texts}
    if not by_digest:
        return {}
    rows = await session.execute(
        select(RuleEmbedding.text_sha256, RuleEmbedding.embedding).where(
            RuleEmbedding.model == model, RuleEmbedding.text_sha256.in_(by_digest)
        )
    )
    return {by_digest[digest]: list(vector) for digest, vector in rows}


async def keep(session: AsyncSession, model: str, vectors: Mapping[str, list[float]]) -> None:
    """Keep the vectors ``model`` made of the texts, in the session's transaction; a vector kept
    meanwhile by another request stays as it is."""
    if not vectors:
        return
    await session.execute(
        insert(RuleEmbedding)
        .values(
            [
                {"model": model, "text_sha256": _digest(text), "embedding": vector}
                for text, vector in vectors.items()
            ]
        )
        .on_conflict_do_nothing()
    )
