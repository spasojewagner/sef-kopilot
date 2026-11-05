"""Ingesting the corpus: making the database's corpus hold exactly what ``corpus/`` holds
(ADR-0020). ``python -m sef_api.rag.ingest``, or ``make ingest``.

An ingest can run any number of times. A document or a passage the database holds as the corpus
does is left alone; a changed one is updated; one the corpus no longer has is deleted. A
passage whose words changed loses its embedding. Then, if an embedder is configured, every
passage without an embedding of its model is embedded, a batch at a time, each batch committed
on its own: an ingest that stops halfway continues where it stopped the next time. A vector is
stored only if the passage still says what was embedded. Two ingests take turns.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from dataclasses import dataclass, fields
from datetime import date
from itertools import batched
from pathlib import Path
from typing import Any, Final

from sqlalchemy import delete, insert, select, update
from sqlalchemy.dialects.postgresql import insert as upsert
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.db import Database
from sef_api.locks import lock_corpus
from sef_api.models import CorpusDocument, CorpusPassage
from sef_api.rag.corpus import Corpus, CorpusError, DatedPassage, load_corpus
from sef_api.rag.embeddings import Embedder, EmbeddingError, embedder_for
from sef_api.settings import Settings

__all__ = ["CORPUS", "Tally", "embedding_text", "ingest", "main"]

#: The corpus of the repository this module belongs to.
CORPUS: Final = Path(__file__).resolve().parents[5] / "corpus"
#: Passages embedded in one request and committed in one transaction.
BATCH: Final = 32

#: The columns of a passage that the corpus decides; the embedding is the database's own.
_PASSAGE_COLUMNS: Final = (
    "id",
    "document",
    "key",
    "label",
    "heading",
    "part",
    "text",
    "amended_by",
    "valid_from",
    "valid_to",
    "fully_from",
    "version",
    "source_url",
    "search_text",
    "text_sha256",
)


@dataclass
class Tally:
    """What an ingest did."""

    documents: int = 0
    added: int = 0
    changed: int = 0
    unchanged: int = 0
    removed: int = 0
    embedded: int = 0

    def __str__(self) -> str:
        return ", ".join(f"{field.name} {getattr(self, field.name)}" for field in fields(self))


def _passage_row(passage: DatedPassage) -> dict[str, Any]:
    return {
        "id": passage.id,
        "document": passage.document,
        "key": passage.key,
        "label": passage.label,
        "heading": passage.heading,
        "part": passage.part,
        "text": passage.text,
        "amended_by": list(passage.amended_by),
        "valid_from": passage.valid_from,
        "valid_to": passage.valid_to,
        "fully_from": passage.fully_from,
        "version": passage.version,
        "source_url": passage.source_url,
        "search_text": passage.search_text,
        "text_sha256": passage.text_sha256,
    }


def embedding_text(corpus: Corpus, passage: DatedPassage) -> str:
    """What is embedded for a passage: where it stands, then what it says."""
    title = corpus.document(passage.document).title
    heading = f" {passage.heading}" if passage.heading else ""
    part = f"\n{passage.part}" if passage.part else ""
    return f"{title}, {passage.label}{heading}{part}\n\n{passage.text}"


async def ingest(
    database: Database, corpus: Corpus, embedder: Embedder | None = None, *, batch: int = BATCH
) -> Tally:
    """Make the database's corpus the corpus given, and embed what has no embedding yet.

    Raises :class:`EmbeddingError` when the embedder fails; what was ingested and embedded
    before it stays.
    """
    tally = Tally(documents=len(corpus.documents))
    async with database.sessions() as session, session.begin():
        await lock_corpus(session)
        await _documents(session, corpus)
        await _passages(session, corpus, tally)
    if embedder is not None:
        await _embed(database, corpus, embedder, batch, tally)
    return tally


async def _documents(session: AsyncSession, corpus: Corpus) -> None:
    rows = [
        {
            "key": document.key,
            "title": document.title,
            "kind": document.kind,
            "publisher": document.publisher,
            "language": document.language,
            "page": document.page,
        }
        for document in corpus.documents
    ]
    statement = upsert(CorpusDocument).values(rows)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[CorpusDocument.key],
            set_={name: statement.excluded[name] for name in rows[0] if name != "key"},
        )
    )


async def _passages(session: AsyncSession, corpus: Corpus, tally: Tally) -> None:
    columns = [getattr(CorpusPassage, name) for name in _PASSAGE_COLUMNS]
    stored = {row["id"]: row for row in (await session.execute(select(*columns))).mappings().all()}
    added: list[dict[str, Any]] = []
    #: Changed passages that keep their embedding, and those whose words changed.
    restated: list[dict[str, Any]] = []
    reworded: list[dict[str, Any]] = []
    for passage in corpus.passages:
        row = _passage_row(passage)
        before = stored.pop(passage.id, None)
        if before is None:
            added.append(row)
        elif before["text_sha256"] != row["text_sha256"]:
            reworded.append(row | {"embedding": None, "embedding_model": None})
        elif dict(before) != row:
            restated.append(row)
        else:
            tally.unchanged += 1
    for statement, rows in ((insert, added), (update, restated), (update, reworded)):
        if rows:
            await session.execute(statement(CorpusPassage), rows)
    if stored:
        await session.execute(delete(CorpusPassage).where(CorpusPassage.id.in_(stored)))
    keys = [document.key for document in corpus.documents]
    await session.execute(delete(CorpusDocument).where(CorpusDocument.key.not_in(keys)))
    tally.added, tally.removed = len(added), len(stored)
    tally.changed = len(restated) + len(reworded)


async def _embed(
    database: Database, corpus: Corpus, embedder: Embedder, batch: int, tally: Tally
) -> None:
    passages = {passage.id: passage for passage in corpus.passages}
    async with database.sessions() as session:
        pending = await session.scalars(
            select(CorpusPassage.id)
            .where(CorpusPassage.embedding_model.is_distinct_from(embedder.model))
            .order_by(CorpusPassage.id)
        )
        waiting = [passages[id_] for id_ in pending if id_ in passages]
    for chunk in batched(waiting, batch):
        vectors = await embedder.passages([embedding_text(corpus, passage) for passage in chunk])
        async with database.sessions() as session, session.begin():
            for passage, vector in zip(chunk, vectors, strict=True):
                stored_id = await session.scalar(
                    update(CorpusPassage)
                    .where(
                        CorpusPassage.id == passage.id,
                        CorpusPassage.text_sha256 == passage.text_sha256,
                    )
                    .values(embedding=vector, embedding_model=embedder.model)
                    .returning(CorpusPassage.id)
                )
                tally.embedded += stored_id is not None


async def _run(settings: Settings, corpus: Corpus, embedder: Embedder | None) -> Tally:
    database = Database.connect(settings.database_url.get_secret_value(), pooled=False)
    try:
        return await ingest(database, corpus, embedder)
    finally:
        await database.engine.dispose()
        if embedder is not None:
            await embedder.aclose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m sef_api.rag.ingest",
        description="Load the corpus into the database named by DATABASE_URL, embedding it "
        "when EMBEDDINGS_PROVIDER names a provider.",
    )
    parser.add_argument("--corpus", type=Path, default=CORPUS, help="the corpus directory")
    arguments = parser.parse_args(argv)
    try:
        corpus = load_corpus(arguments.corpus)
    except CorpusError as error:
        sys.stderr.write(f"error: {error}\n")
        return 1
    settings = Settings()
    embedder = embedder_for(settings)
    try:
        tally = asyncio.run(_run(settings, corpus, embedder))
    except EmbeddingError as error:
        sys.stderr.write(f"error: the corpus is ingested, but not all of it embedded: {error}\n")
        return 1
    today = date.today()  # noqa: DTZ011  # a calendar day, for the people reading the output
    applying = len(corpus.on(today))
    sys.stdout.write(f"ingested the corpus: {tally}; {applying} passages apply today\n")
    if embedder is None:
        sys.stdout.write("no embeddings: EMBEDDINGS_PROVIDER is none\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
