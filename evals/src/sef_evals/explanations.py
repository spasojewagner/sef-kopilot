"""The explanations' evaluations: the rules of the golden documents explained by the model, and
the passages their explanations cite (ADR-0055).

``evals/golden/explanations.yaml`` names the documents whose rules are explained, the
languages, the day they are explained on, which dates what applies, and for each rule the
passages a person labelled relevant to it, or not. Every rule a document breaks under SRB-CIUS
is explained as the API explains a report, from the passages retrieval finds, without
embeddings, by the model of a cassette (:mod:`sef_evals.cassettes`).

- ``explained``: the rules explained, of those asked for;
- ``citation_resolution``: the citations that name a passage stored in the corpus and applying
  on the day, of all citations (the brief's guardrail: 100 %);
- ``citation_relevance``: the citations of a passage labelled relevant to the rule, of all
  citations; one of a passage that no label names counts against it, so that the labels keep
  up with what retrieval finds.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import and_, or_, select

from einvoice_core.pipeline import validate
from einvoice_core.violations import Violation
from sef_api.db import Database
from sef_api.llm import Language, LLMClient
from sef_api.models import CorpusPassage
from sef_api.rag.explainer import Explainer, Explanation, explain_report
from sef_api.rag.retrieval import Found, Retriever
from sef_evals.golden import GoldenError
from sef_evals.measures import Measure

__all__ = [
    "Asked",
    "ExplanationGolden",
    "Labels",
    "explain",
    "load_golden",
    "measure",
    "unlabelled",
]

#: Rules explained per document: every one, as no golden document breaks more.
_MAX_RULES = 100
#: Seconds the rules of one document may take: the real model is slow and waits for its limits.
_SECONDS = 600.0


class Labels(BaseModel):
    """The passages a person labelled relevant to a rule, and those labelled not."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    relevant: frozenset[str] = frozenset()
    not_relevant: frozenset[str] = frozenset()


class ExplanationGolden(BaseModel):
    """The golden set of the explanations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    day: date
    languages: tuple[Language, ...] = Field(min_length=1)
    documents: tuple[str, ...] = Field(min_length=1)
    exclude: tuple[str, ...] = ()
    rules: dict[str, Labels]

    @field_validator("rules")
    @classmethod
    def _apart(cls, rules: dict[str, Labels]) -> dict[str, Labels]:
        for rule, labels in rules.items():
            if both := labels.relevant & labels.not_relevant:
                raise ValueError(f"{rule}: {', '.join(sorted(both))} labelled both ways")
        return rules

    def paths(self, root: Path) -> list[str]:
        """The documents, from the repository's root, without those excluded."""

        def matched(patterns: Sequence[str]) -> list[str]:
            found: list[str] = []
            for pattern in patterns:
                paths = sorted(root.glob(pattern))
                if not paths:
                    raise GoldenError(f"explanations: {pattern!r} names no document")
                found += [path.relative_to(root).as_posix() for path in paths]
            return found

        excluded = set(matched(self.exclude))
        return [p for p in dict.fromkeys(matched(self.documents)) if p not in excluded]


def load_golden(path: Path) -> ExplanationGolden:
    try:
        return ExplanationGolden.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (yaml.YAMLError, ValidationError) as error:
        raise GoldenError(f"{path.name}: {error}") from None


@dataclass(frozen=True)
class Asked:
    """A rule of a document explained in a language, and what came of it."""

    document: str
    language: Language
    explanation: Explanation

    @property
    def id(self) -> str:
        return f"{self.document} [{self.language}] {self.explanation.rule_id}"


async def explain(
    root: Path,
    golden: ExplanationGolden,
    database: Database,
    llm: LLMClient,
    *,
    progress: Callable[[str], None] | None = None,
) -> list[Asked]:
    """Every rule of the golden documents, explained in each language as the API explains a
    report; the model is ``llm``. ``progress`` is told each document and language in turn."""
    explainer = Explainer(llm)
    asked: list[Asked] = []
    for document in golden.paths(root):
        report = validate(root / document, "srb")
        for language in golden.languages:
            if progress is not None:
                progress(f"the rules of {document} [{language}]")
            async with database.sessions() as session:
                explanations, _ = await explain_report(
                    session,
                    report,
                    day=golden.day,
                    language=language,
                    explainer=explainer,
                    embedder=None,
                    max_rules=_MAX_RULES,
                    seconds=_SECONDS,
                )
            asked += [Asked(document, language, explanation) for explanation in explanations]
    return asked


async def _stored(database: Database, ids: set[str], day: date) -> set[str]:
    """Of ``ids``, those of passages stored in the corpus that apply on ``day``."""
    if not ids:
        return set()
    async with database.sessions() as session:
        found = await session.scalars(
            select(CorpusPassage.id).where(
                CorpusPassage.id.in_(ids),
                and_(
                    CorpusPassage.valid_from <= day,
                    or_(CorpusPassage.valid_to.is_(None), CorpusPassage.valid_to > day),
                ),
            )
        )
        return set(found)


async def measure(
    golden: ExplanationGolden, database: Database, asked: Sequence[Asked]
) -> list[Measure]:
    """The explanations' measures on what was ``asked``."""
    explained = [a for a in asked if a.explanation.problem is None]
    cited = [(a, citation.id) for a in explained for citation in a.explanation.citations]
    stored = await _stored(database, {passage for _, passage in cited}, golden.day)
    irrelevant = []
    for a, passage in cited:
        labels = golden.rules.get(a.explanation.rule_id, Labels())
        if passage in labels.not_relevant:
            irrelevant.append(f"{a.id}: cites {passage}, labelled not relevant")
        elif passage not in labels.relevant:
            irrelevant.append(f"{a.id}: cites {passage}, which no label names")
    return [
        Measure(
            name="explained",
            title="Rules of the golden documents that the model explained",
            kind="share",
            total=len(asked),
            failures=tuple(
                f"{a.id}: {a.explanation.problem}" for a in asked if a.explanation.problem
            ),
        ),
        Measure(
            name="citation_resolution",
            title="Citations of a passage stored in the corpus and applying on the day",
            kind="share",
            total=len(cited),
            failures=tuple(f"{a.id}: cites {p}, not stored" for a, p in cited if p not in stored),
        ),
        Measure(
            name="citation_relevance",
            title="Citations of a passage labelled relevant to the rule",
            kind="share",
            total=len(cited),
            failures=tuple(irrelevant),
        ),
    ]


async def unlabelled(
    root: Path, golden: ExplanationGolden, database: Database
) -> dict[str, list[Found]]:
    """By rule, the passages retrieval finds for the golden documents that no label names:
    those a person is to label before the model may cite them."""
    found: dict[str, dict[str, Found]] = {}
    async with database.sessions() as session:
        retriever = Retriever(session, golden.day)
        for document in golden.paths(root):
            first: dict[str, Violation] = {}
            for violation in validate(root / document, "srb").violations:
                first.setdefault(violation.rule_id, violation)
            for rule, violation in first.items():
                labels = golden.rules.get(rule, Labels())
                for passage in await retriever.passages(violation):
                    if passage.id not in labels.relevant | labels.not_relevant:
                        found.setdefault(rule, {})[passage.id] = passage
    return {rule: list(passages.values()) for rule, passages in sorted(found.items())}
