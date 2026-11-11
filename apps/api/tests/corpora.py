"""The corpus stored for tests, and stand-ins for the language model that explains with it."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from functools import cache
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.llm import LLMError, Message
from sef_api.models import CorpusDocument, CorpusPassage
from sef_api.rag.corpus import Corpus, DatedPassage, load_corpus
from sef_api.rag.ingest import CORPUS


@cache
def repository_corpus() -> Corpus:
    """The corpus of the repository, read once."""
    return load_corpus(CORPUS)


async def store_corpus(
    session: AsyncSession,
    corpus: Corpus,
    *,
    embed: Callable[[DatedPassage], list[float] | None] | None = None,
    model: str = "test/embedder",
) -> None:
    """Store ``corpus`` in ``session`` as the ingest stores it, each passage with the embedding
    ``embed`` gives it, by ``model``, if any."""
    session.add_all(
        CorpusDocument(
            key=document.key,
            title=document.title,
            kind=document.kind,
            publisher=document.publisher,
            language=document.language,
            page=document.page,
        )
        for document in corpus.documents
    )
    await session.flush()
    for passage in corpus.passages:
        vector = embed(passage) if embed is not None else None
        session.add(
            CorpusPassage(
                id=passage.id,
                document=passage.document,
                key=passage.key,
                label=passage.label,
                heading=passage.heading,
                part=passage.part,
                amended_by=list(passage.amended_by),
                valid_from=passage.valid_from,
                valid_to=passage.valid_to,
                fully_from=passage.fully_from,
                version=passage.version,
                source_url=passage.source_url,
                search_text=passage.search_text,
                text_sha256=passage.text_sha256,
                embedding=vector,
                embedding_model=model if vector is not None else None,
                text=passage.text,
            )
        )
    await session.flush()


class ScriptedModel:
    """A language model that gives the answers a test wrote, in turn, and notes what it was
    asked. An answer that is an exception is raised instead."""

    model = "test/scripted"

    def __init__(self, *answers: str | Exception) -> None:
        self.answers = list(answers)
        self.asked: list[list[Message]] = []
        self.schemas: list[tuple[str, Mapping[str, Any]]] = []
        self.most: list[int | None] = []

    async def answer(
        self,
        messages: Sequence[Message],
        *,
        name: str,
        schema: Mapping[str, Any],
        max_tokens: int | None = None,
    ) -> str:
        self.asked.append(list(messages))
        self.schemas.append((name, schema))
        self.most.append(max_tokens)
        if not self.answers:
            raise LLMError("the test gave no more answers")
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def aclose(self) -> None:
        pass


class QuotingModel:
    """A language model that explains every rule alike and cites the first two passages it may:
    what a test application explains with."""

    model = "test/quoting"

    def __init__(self) -> None:
        self.asked: list[tuple[str, list[Message]]] = []

    async def answer(
        self,
        messages: Sequence[Message],
        *,
        name: str,
        schema: Mapping[str, Any],
        max_tokens: int | None = None,  # noqa: ARG002
    ) -> str:
        self.asked.append((name, list(messages)))
        given: list[str] = schema["properties"]["citations"]["items"]["enum"]
        return json.dumps(
            {
                "explanation": "Pravilo traži element koji faktura nema.",
                "fix": "Dodajte element sa ispravnom vrednošću.",
                "citations": given[:2],
            }
        )

    async def aclose(self) -> None:
        pass


class ReadingModel:
    """A language model that reads every document as the same invoice: what a test application
    reads PDFs and pictures with."""

    model = "test/reading"

    def __init__(self) -> None:
        self.asked: list[list[Message]] = []

    async def answer(
        self,
        messages: Sequence[Message],
        *,
        name: str,  # noqa: ARG002
        schema: Mapping[str, Any],  # noqa: ARG002
        max_tokens: int | None = None,  # noqa: ARG002
    ) -> str:
        self.asked.append(list(messages))
        return json.dumps(
            {"number": "RF-2026-000123", "issue_date": "2026-10-05", "currency": "RSD"}
        )

    async def aclose(self) -> None:
        pass
