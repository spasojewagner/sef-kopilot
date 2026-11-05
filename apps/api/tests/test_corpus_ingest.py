"""Ingesting the corpus: the database holds exactly the corpus, a second ingest changes nothing,
passages are embedded once and again when their words change, an interrupted ingest continues,
and two ingests take turns."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import func, select, update
from sqlalchemy import text as sql

from sef_api.db import Database
from sef_api.locks import lock_corpus
from sef_api.models import CorpusDocument, CorpusPassage
from sef_api.rag.corpus import Corpus, Passage, load_corpus, render_edition
from sef_api.rag.embeddings import DIMENSIONS, EmbeddingError
from sef_api.rag.ingest import CORPUS, Tally, embedding_text, ingest, main

pytestmark = pytest.mark.usefixtures("committed_database")


class FakeEmbedder:
    """Vectors made from the length of each text; it notes every batch, and can stop working."""

    def __init__(self, model: str = "fake/model/1024", *, fails_at: int | None = None) -> None:
        self.model = model
        self.batches: list[list[str]] = []
        self.fails_at = fails_at

    async def passages(self, texts: Sequence[str]) -> list[list[float]]:
        if self.fails_at is not None and len(self.batches) == self.fails_at:
            raise EmbeddingError("the service is down")
        self.batches.append(list(texts))
        return [[float(len(text))] + [0.0] * (DIMENSIONS - 1) for text in texts]

    async def query(self, text: str) -> list[float]:
        return (await self.passages([text]))[0]

    async def aclose(self) -> None:
        pass


MANIFEST = """\
[[documents]]
key = "law"
title = "Zakon"
kind = "law"
publisher = "Narodna skupština"
language = "sr-Cyrl"
page = "https://example.org/law"
source_format = "pis-html"

[[documents.editions]]
file = "law/2026-04-01.md"
valid_from = 2026-04-01
version = "1/2026"
source_url = "https://example.org/law"
source_file = "law.html"
sha256 = "{sha}"
fetched_at = 2026-11-05
"""

LIST = """
[[documents]]
key = "list"
title = "Spisak"
kind = "list"
publisher = "Ministarstvo finansija"
language = "sr-Cyrl"
page = "https://example.org/list"
source_format = "tax-categories-pdf"

[[documents.editions]]
file = "list/2024-09-01.md"
valid_from = 2024-09-01
version = "01.09.2024"
source_url = "https://example.org/list"
source_file = "list.pdf"
sha256 = "{sha}"
fetched_at = 2026-11-05
"""


def article(number: int, text: str) -> Passage:
    return Passage(key=f"Article {number}", label=f"Члан {number}.", text=text)


def small_corpus(
    directory: Path, articles: Sequence[Passage], *, version: str = "1/2026", listed: bool = True
) -> Corpus:
    """A corpus of a law with ``articles`` and, if ``listed``, a list of one entry."""
    manifest = MANIFEST.replace('version = "1/2026"', f'version = "{version}"')
    (directory / "law").mkdir(exist_ok=True)
    (directory / "law/2026-04-01.md").write_text(render_edition("Zakon", articles), "utf-8")
    if listed:
        manifest += LIST
        (directory / "list").mkdir(exist_ok=True)
        entry = Passage(key="Tax category S20", label="Пореска категорија S20", text="PDV-RS-OBJ")
        (directory / "list/2024-09-01.md").write_text(render_edition("Spisak", [entry]), "utf-8")
    (directory / "manifest.toml").write_text(manifest.format(sha="a" * 64), "utf-8")
    return load_corpus(directory)


async def stored(database: Database) -> dict[str, tuple[str, str, bool]]:
    """Each stored passage's id, with its text, its version and whether it has an embedding."""
    async with database.sessions() as session:
        rows = await session.execute(
            select(
                CorpusPassage.id,
                CorpusPassage.text,
                CorpusPassage.version,
                CorpusPassage.embedding_model.is_not(None),
            )
        )
        return {id_: (text, version, embedded) for id_, text, version, embedded in rows}


async def test_the_repositorys_corpus_is_ingested_and_a_second_ingest_changes_nothing(
    committed_database: Database,
) -> None:
    corpus = load_corpus(CORPUS)

    first = await ingest(committed_database, corpus)
    second = await ingest(committed_database, corpus)

    assert first == Tally(documents=5, added=len(corpus.passages))
    assert second == Tally(documents=5, unchanged=len(corpus.passages))
    async with committed_database.sessions() as session:
        count = await session.scalar(select(func.count()).select_from(CorpusPassage))
        row = await session.get(CorpusPassage, "srb-cius/1-3-table-1-bt-3/2025-06-06")
    assert count == len(corpus.passages)
    assert row is not None
    assert row.label == "BT-3"
    assert row.search_text.startswith("bt-3 invoice type code — sifra vrste fakture")
    assert row.embedding is None


async def test_an_ingest_makes_the_database_hold_exactly_the_corpus(
    committed_database: Database, tmp_path: Path
) -> None:
    await ingest(committed_database, small_corpus(tmp_path, [article(1, "А"), article(2, "Б")]))
    changed = small_corpus(
        tmp_path, [article(1, "А"), article(3, "В")], version="1/2026 i 2/2026", listed=False
    )
    publisher = "Narodna skupština Republike Srbije"

    tally = await ingest(
        committed_database, Corpus((replace(changed.document("law"), publisher=publisher),))
    )

    assert tally == Tally(documents=1, added=1, changed=1, removed=2)
    assert await stored(committed_database) == {
        "law/article-1/2026-04-01": ("А", "1/2026 i 2/2026", False),
        "law/article-3/2026-04-01": ("В", "1/2026 i 2/2026", False),
    }
    async with committed_database.sessions() as session:
        documents = await session.execute(select(CorpusDocument.key, CorpusDocument.publisher))
        assert [tuple(document) for document in documents] == [("law", publisher)]


async def test_passages_are_embedded_once_and_again_when_their_words_change(
    committed_database: Database, tmp_path: Path
) -> None:
    corpus = small_corpus(tmp_path, [article(1, "А"), article(2, "Б")])
    embedder = FakeEmbedder()

    assert (await ingest(committed_database, corpus, embedder, batch=2)).embedded == 3
    assert (await ingest(committed_database, corpus, embedder)).embedded == 0
    assert len(embedder.batches) == 2

    reworded = small_corpus(tmp_path, [article(1, "А"), article(2, "Б, другачије")])
    tally = await ingest(committed_database, reworded, embedder)

    assert (tally.changed, tally.embedded) == (1, 1)
    assert embedder.batches[-1] == ["Zakon, Члан 2.\n\nБ, другачије"]
    async with committed_database.sessions() as session:
        row = await session.get(CorpusPassage, "law/article-2/2026-04-01")
    assert row is not None
    assert row.embedding == [float(len("Zakon, Члан 2.\n\nБ, другачије"))] + [0.0] * 1023
    assert row.embedding_model == "fake/model/1024"


async def test_another_model_embeds_every_passage_again(
    committed_database: Database, tmp_path: Path
) -> None:
    corpus = small_corpus(tmp_path, [article(1, "А")])
    await ingest(committed_database, corpus, FakeEmbedder("fake/model/1024"))

    assert (await ingest(committed_database, corpus, FakeEmbedder("fake/other/1024"))).embedded == 2


async def test_an_ingest_whose_embedder_fails_continues_where_it_stopped(
    committed_database: Database, tmp_path: Path
) -> None:
    corpus = small_corpus(tmp_path, [article(number, "текст") for number in range(1, 5)])

    with pytest.raises(EmbeddingError):
        await ingest(committed_database, corpus, FakeEmbedder(fails_at=1), batch=2)

    embedded = [id_ for id_, (_, _, has) in (await stored(committed_database)).items() if has]
    assert len(embedded) == 2  # the first batch, committed before the second failed
    rest = FakeEmbedder()
    assert (await ingest(committed_database, corpus, rest, batch=2)).embedded == 3
    assert all(has for _, _, has in (await stored(committed_database)).values())


async def test_an_embedding_is_kept_only_for_the_words_it_was_made_of(
    committed_database: Database, tmp_path: Path
) -> None:
    corpus = small_corpus(tmp_path, [article(1, "А")], listed=False)
    await ingest(committed_database, corpus)

    class Meddling(FakeEmbedder):
        async def passages(self, texts: Sequence[str]) -> list[list[float]]:
            # another ingest changes the passage while this one embeds it
            async with committed_database.sessions() as session, session.begin():
                await session.execute(update(CorpusPassage).values(text_sha256="0" * 64))
            return await super().passages(texts)

    assert (await ingest(committed_database, corpus, Meddling())).embedded == 0
    assert (await stored(committed_database))["law/article-1/2026-04-01"][2] is False


async def test_two_ingests_at_once_take_turns(committed_database: Database, tmp_path: Path) -> None:
    corpus = small_corpus(tmp_path, [article(number, "текст") for number in range(1, 30)])

    first, second = await asyncio.gather(
        ingest(committed_database, corpus), ingest(committed_database, corpus)
    )

    assert sorted([first.added, second.added]) == [0, 30]
    assert sorted([first.unchanged, second.unchanged]) == [0, 30]


async def test_an_ingest_waits_for_the_one_under_way(
    committed_database: Database, tmp_path: Path
) -> None:
    # Two ingests of one corpus would also wait for each other on its documents' rows; the
    # lock orders any two, whatever documents they hold.
    corpus = small_corpus(tmp_path, [article(1, "текст")])

    async def waiting_for_a_lock() -> bool:
        async with committed_database.sessions() as session:
            return bool(
                await session.scalar(
                    sql(
                        "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted"
                        " AND database = (SELECT oid FROM pg_database"
                        " WHERE datname = current_database())"
                    )
                )
            )

    async with committed_database.sessions() as session, session.begin():
        await lock_corpus(session)
        second = asyncio.create_task(ingest(committed_database, corpus))
        async with asyncio.timeout(10):
            while not second.done() and not await waiting_for_a_lock():
                await asyncio.sleep(0.01)
        assert not second.done()

    assert (await second).added == 2


def test_what_is_embedded_says_where_a_passage_stands_then_what_it_says(tmp_path: Path) -> None:
    corpus = small_corpus(
        tmp_path,
        [Passage(key="Article 1", label="Члан 1.", heading="Предмет", part="I. ДЕО", text="Т")],
    )

    assert embedding_text(corpus, corpus.passages[0]) == "Zakon, Члан 1. Предмет\nI. ДЕО\n\nТ"


def test_the_command_ingests_the_corpus_into_the_database_of_the_settings(
    database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    small_corpus(tmp_path, [article(1, "А")])
    monkeypatch.chdir(tmp_path)  # no .env
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("EMBEDDINGS_PROVIDER", "none")

    assert main(["--corpus", str(tmp_path)]) == 0
    assert "added 2" in capsys.readouterr().out

    (tmp_path / "law/2026-04-01.md").write_text("# Zakon\n", encoding="utf-8")
    assert main(["--corpus", str(tmp_path)]) == 1
    assert "an edition without passages" in capsys.readouterr().err


def test_the_command_says_when_the_corpus_is_ingested_but_not_embedded(
    database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    small_corpus(tmp_path, [article(1, "А")])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", database_url)
    failing = FakeEmbedder(fails_at=0)
    monkeypatch.setattr("sef_api.rag.ingest.embedder_for", lambda _settings: failing)

    assert main(["--corpus", str(tmp_path)]) == 1
    assert "ingested, but not all of it embedded: the service is down" in capsys.readouterr().err


def test_the_command_embeds_the_corpus_with_the_embedder_of_the_settings(
    database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    small_corpus(tmp_path, [article(1, "А")])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", database_url)
    embedder = FakeEmbedder()
    monkeypatch.setattr("sef_api.rag.ingest.embedder_for", lambda _settings: embedder)

    assert main(["--corpus", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "embedded 2" in out
    assert "no embeddings" not in out
