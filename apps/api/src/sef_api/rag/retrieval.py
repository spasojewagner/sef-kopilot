"""Retrieval: the stored passages that one violation concerns, among those that apply on a day
(ADR-0021).

Five ways find passages, in the order their answers are trusted:

1. **the rule's references**: an SRB-CIUS rule names the passages it is authored from
   (:mod:`sef_api.rag.citations`), and nothing can be more relevant;
2. **the semantic terms**: ``BT-112`` in a violation's message, or among an SRB-CIUS rule's
   terms, is the row of the specification's tables that defines that term;
3. **the place**: the violation's XPath, without its positions, is the UBL path of a row of the
   specification, or the nearest row above it;
4. **the codes**: a rule that cites the Ministry's list of tax categories finds the categories
   its message names (``S20``, ``O``), and an exemption code (``PDV-RS-11-1``) finds the
   category whose list holds it;
5. **the words and the meaning**: the message against the passages' text folded to Latin
   letters (``pg_trgm``), and the embedding of what the rule says against theirs
   (``pgvector``) when the corpus is embedded, the two lists fused by their ranks. The words
   of a message of the XML parser or the schema are left out: they name elements, which the
   place finds better, among words that every row shares.

Each passage is found once, where the first way that found it puts it, up to a limit. What is
found is read from the database, so that whatever an explanation cites is a stored passage.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Final

from sqlalchemy import ColumnElement, and_, func, literal, or_, select, text, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from einvoice_core.arithmetic import STATEMENTS
from einvoice_core.srb import RULES
from einvoice_core.violations import Violation
from sef_api.db import Vector
from sef_api.models import CorpusDocument, CorpusPassage
from sef_api.rag.citations import WHOLE_DOCUMENTS, keys_of
from sef_api.rag.embeddings import DIMENSIONS
from sef_api.rag.text import fold

__all__ = [
    "PASSAGES",
    "WORD_SIMILARITY",
    "Found",
    "Retriever",
    "document_path",
    "meaning_text",
    "query_text",
]

#: The most passages found for one violation: enough for a rule and the terms it names, few
#: enough to keep what a model is sent short.
PASSAGES: Final = 6
#: How much of a passage's words a message must share for the words alone to find it.
WORD_SIMILARITY: Final = 0.3
#: How many passages the words and the meaning each propose before they are fused.
_PROPOSED: Final = 4
#: The constant of reciprocal rank fusion: a passage scores 1 / (60 + rank) in each list.
_FUSION: Final = 60

#: The corpus's documents whose passages the second to fourth ways find (corpus/manifest.toml).
SPECIFICATION: Final = "srb-cius"
TAX_CATEGORIES: Final = "tax-categories"

_TERM: Final = re.compile(r"\bB[TG]-E?\d+\b")
_ROW: Final = re.compile(r"^[\d.]+, Table \d+, (?P<terms>.+)$")
_PATH: Final = re.compile(r"/(?:Invoice|CreditNote)(?:/[A-Za-z]+:[A-Za-z]+)+(?:/@[A-Za-z]+)?")
_POSITION: Final = re.compile(r"\[\d+\]")
_ROOTS: Final = {"ubl:Invoice": "Invoice", "cn:CreditNote": "CreditNote"}
_CATEGORY: Final = re.compile(r"^Tax category (?P<code>[A-Z0-9]+)$")
_EXEMPTION: Final = re.compile(r"\bPDV-RS-[0-9A-Z]+(?:-[0-9A-Z]+)*")
_RULE_PREFIX: Final = re.compile(r"^\s*\[[A-Z0-9-]+\]\s*-?\s*")

_RULES: Final = {rule.id: rule for rule in RULES}
#: The layers whose messages are the XML parser's and the schema's (libxml2's).
_PARSER_LAYERS: Final = frozenset({"xml", "xsd"})


@dataclass(frozen=True)
class Found:
    """A stored passage that applies on the day, as an explanation may cite it."""

    id: str
    document: str
    title: str
    key: str
    label: str
    heading: str | None
    text: str
    version: str
    source_url: str
    valid_from: date
    valid_to: date | None


def document_path(xpath: str | None) -> str | None:
    """The violation's place as the specification writes UBL paths: without positions, and
    without a prefix on the root. ``/ubl:Invoice/cac:InvoiceLine[2]/cbc:ID`` is
    ``/Invoice/cac:InvoiceLine/cbc:ID``; a place outside an invoice or a credit note is None."""
    if not xpath:
        return None
    steps = _POSITION.sub("", xpath).strip("/").split("/")
    if steps[0] not in _ROOTS:
        return None
    return "/" + "/".join([_ROOTS[steps[0]], *steps[1:]])


def query_text(violation: Violation) -> str:
    """What the words search with: the message, without the rule's identifier that EN 16931
    and Peppol put before it (``[BR-CO-15]-``)."""
    return _RULE_PREFIX.sub("", violation.message, count=1)


def meaning_text(violation: Violation) -> str | None:
    """What the meaning searches with: what the rule says, never what the violation found, so
    that an embedder is sent public text only (ADR-0021).

    A Schematron rule's message is its rule set's own words, which quote nothing of the
    document; an SRB-CIUS rule has its title, and an arithmetic rule its statement, in place
    of a message that quotes amounts and identifiers. The XML parser's and the schema's
    messages quote the document, and have nothing to say in its place.
    """
    if violation.layer == "schematron":
        return query_text(violation)
    if violation.layer == "srb-cius":
        rule = _RULES.get(violation.rule_id)
        return rule.title if rule is not None else None
    if violation.layer == "arithmetic":
        return STATEMENTS.get(violation.rule_id)
    return None


def _applies(day: date) -> ColumnElement[bool]:
    return and_(
        CorpusPassage.valid_from <= day,
        or_(CorpusPassage.valid_to.is_(None), CorpusPassage.valid_to > day),
    )


@dataclass
class _Anchors:
    """The passages the terms, the places and the codes point at, for one day."""

    terms: dict[str, list[str]] = field(default_factory=dict)
    paths: dict[str, list[str]] = field(default_factory=dict)
    categories: dict[str, str] = field(default_factory=dict)
    lists: dict[str, str] = field(default_factory=dict)

    def add(self, passage_id: str, document: str, key: str, passage_text: str) -> None:
        if document == SPECIFICATION and (row := _ROW.match(key)):
            for term in row["terms"].split(", "):
                self.terms.setdefault(term, []).append(passage_id)
            for path in dict.fromkeys(_PATH.findall(passage_text)):
                self.paths.setdefault(path, []).append(passage_id)
        elif document == TAX_CATEGORIES and (category := _CATEGORY.match(key)):
            self.categories[category["code"]] = passage_id
            self.lists[passage_id] = passage_text

    def place(self, path: str | None) -> list[str]:
        """The rows of the place, or of the nearest place above it that has rows; the root
        alone is no place."""
        steps = path.split("/")[1:] if path else []
        while len(steps) > 1:
            if found := self.paths.get("/" + "/".join(steps)):
                return found
            steps.pop()
        return []


class Retriever:
    """Finds the passages of violations among those that apply on ``day``, in ``session``.

    The specification's rows and the tax categories are read once, with the first violation,
    and kept for the next ones.
    """

    def __init__(self, session: AsyncSession, day: date, *, limit: int = PASSAGES) -> None:
        self._session = session
        self._day = day
        self._limit = limit
        self._anchors: _Anchors | None = None

    async def passages(
        self,
        violation: Violation,
        *,
        vector: Sequence[float] | None = None,
        model: str | None = None,
    ) -> list[Found]:
        """The passages ``violation`` concerns, most relevant first. ``vector`` is the
        embedding of :func:`meaning_text`, by ``model``, when the corpus is embedded."""
        anchors = await self._read_anchors()
        rule = _RULES.get(violation.rule_id)
        query = query_text(violation)
        found: list[str] = []
        found += await self._referenced(violation.rule_id)
        terms = [*_TERM.findall(violation.message), *(rule.terms if rule else ())]
        found += [passage for term in terms for passage in anchors.terms.get(term, [])]
        found += anchors.place(document_path(violation.xpath))
        if rule is not None and any(
            reference.document == TAX_CATEGORIES for reference in rule.references
        ):
            found += [
                anchors.categories[code]
                for code in re.findall(r"\b[A-Z][A-Z0-9]*\b", violation.message)
                if code in anchors.categories
            ]
        found += [
            passage
            for code in _EXEMPTION.findall(violation.message)
            for passage, codes in anchors.lists.items()
            if re.search(rf"(?<![0-9A-Z-]){re.escape(code)}(?![0-9A-Z-])", codes)
        ]
        found += _fused(
            await self._by_words(query) if violation.layer not in _PARSER_LAYERS else [],
            await self._by_meaning(vector, model) if vector is not None and model else [],
        )
        return await self._read(list(dict.fromkeys(found))[: self._limit])

    async def by_words(self, text: str) -> list[Found]:
        """The passages that share enough of ``text``'s words, most alike first: the last of
        the ways a violation's passages are found, for words that come with no violation."""
        return await self._read(await self._by_words(text))

    async def _read_anchors(self) -> _Anchors:
        if self._anchors is None:
            anchors = _Anchors()
            rows = await self._session.execute(
                select(
                    CorpusPassage.id, CorpusPassage.document, CorpusPassage.key, CorpusPassage.text
                ).where(
                    CorpusPassage.document.in_([SPECIFICATION, TAX_CATEGORIES]),
                    _applies(self._day),
                )
            )
            for passage_id, document, key, passage_text in rows:
                anchors.add(passage_id, document, key, passage_text)
            self._anchors = anchors
        return self._anchors

    async def _referenced(self, rule_id: str) -> list[str]:
        """The passages the rule names, in the order it names them; a list it names whole is
        left to the codes its message gives."""
        rule = _RULES.get(rule_id)
        if rule is None:
            return []
        pairs = [
            (reference.document, key)
            for reference in rule.references
            if (reference.document, reference.passage) not in WHOLE_DOCUMENTS
            for key in keys_of(reference)
        ]
        rows = await self._session.execute(
            select(CorpusPassage.document, CorpusPassage.key, CorpusPassage.id).where(
                tuple_(CorpusPassage.document, CorpusPassage.key).in_(pairs), _applies(self._day)
            )
        )
        stored = {(document, key): passage_id for document, key, passage_id in rows}
        return [stored[pair] for pair in pairs if pair in stored]

    async def _by_words(self, query: str) -> list[str]:
        """The passages that share enough of the message's words, by the trigram index."""
        folded = fold(query)
        if not folded.strip():
            return []
        await self._session.execute(
            text("SELECT set_config('pg_trgm.word_similarity_threshold', :value, true)"),
            {"value": str(WORD_SIMILARITY)},
        )
        similarity = func.word_similarity(literal(folded), CorpusPassage.search_text)
        rows = await self._session.scalars(
            select(CorpusPassage.id)
            .where(literal(folded).op("<%")(CorpusPassage.search_text), _applies(self._day))
            .order_by(similarity.desc(), CorpusPassage.id)
            .limit(_PROPOSED)
        )
        return list(rows)

    async def _by_meaning(self, vector: Sequence[float], model: str) -> list[str]:
        """The passages whose embedding by ``model`` is nearest the message's, by cosine."""
        distance = CorpusPassage.embedding.op("<=>")(literal(list(vector), Vector(DIMENSIONS)))
        rows = await self._session.scalars(
            select(CorpusPassage.id)
            .where(CorpusPassage.embedding_model == model, _applies(self._day))
            .order_by(distance, CorpusPassage.id)
            .limit(_PROPOSED)
        )
        return list(rows)

    async def _read(self, ids: list[str]) -> list[Found]:
        if not ids:
            return []
        rows = await self._session.execute(
            select(
                CorpusPassage.id,
                CorpusPassage.document,
                CorpusDocument.title,
                CorpusPassage.key,
                CorpusPassage.label,
                CorpusPassage.heading,
                CorpusPassage.text,
                CorpusPassage.version,
                CorpusPassage.source_url,
                CorpusPassage.valid_from,
                CorpusPassage.valid_to,
            )
            .join(CorpusDocument, CorpusDocument.key == CorpusPassage.document)
            .where(CorpusPassage.id.in_(ids))
        )
        read = {row.id: Found(*row) for row in rows}
        return [read[passage_id] for passage_id in ids if passage_id in read]


def _fused(*rankings: Iterable[str]) -> list[str]:
    """Reciprocal rank fusion: each list gives a passage 1 / (60 + its rank), the sums order
    them, and ties go by id."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, passage in enumerate(ranking, start=1):
            scores[passage] = scores.get(passage, 0.0) + 1 / (_FUSION + rank)
    return sorted(scores, key=lambda passage: (-scores[passage], passage))
