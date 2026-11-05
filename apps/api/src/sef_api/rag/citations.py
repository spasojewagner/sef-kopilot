"""The passages of the corpus that the validator's rules are authored from (ADR-0020).

Every SRB-CIUS rule names the passages it comes from: an :class:`einvoice_core.srb.Reference`,
a document of :data:`einvoice_core.srb.SOURCES` and a passage of it, ``"1.3, Table 1, BT-3"``.
The corpus keys its passages the same way, so a reference names corpus passages directly:

- one passage by its key (``"1.2"``, ``"1.3, Table 1, BT-3"``, ``"Article 2"``);
- several rows of one table (``"1.3, Table 1, BT-95, BT-102, BT-151"``);
- a whole list (``"the list for each tax category"``): every passage of the document.

:func:`passages_for` resolves a reference to the passages that apply on a day, which an
explanation cites by id. A reference that names a passage the corpus does not hold on that day
raises :class:`UnresolvedReferenceError`: a rule can never point at nothing, and the tests
resolve every reference of every rule.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Final

from einvoice_core.srb import RULES, Reference
from sef_api.rag.corpus import Corpus, DatedPassage

__all__ = [
    "WHOLE_DOCUMENTS",
    "UnresolvedReferenceError",
    "keys_of",
    "passages_for",
    "rule_passages",
]

#: References that name a whole document rather than passages of it.
WHOLE_DOCUMENTS: Final = frozenset({("tax-categories", "the list for each tax category")})

_TABLE: Final = re.compile(r"^(?P<table>[\d.]+, Table \d+), (?P<rows>.+)$")


class UnresolvedReferenceError(LookupError):
    """A reference names a passage that the corpus does not hold on the day asked about."""


def keys_of(reference: Reference) -> tuple[str, ...]:
    """The keys of the passages a reference names, in its order (none for a whole document)."""
    if (reference.document, reference.passage) in WHOLE_DOCUMENTS:
        return ()
    if match := _TABLE.match(reference.passage):
        rows = match.group("rows").split(", ")
        return tuple(f"{match.group('table')}, {row}" for row in rows)
    return (reference.passage,)


def passages_for(corpus: Corpus, reference: Reference, day: date) -> tuple[DatedPassage, ...]:
    """The passages a reference names that apply on ``day``."""
    keys = keys_of(reference)
    if not keys:
        found = tuple(p for p in corpus.on(day) if p.document == reference.document)
    else:
        found = tuple(
            passage
            for key in keys
            if (passage := corpus.passage(reference.document, key, day)) is not None
        )
    if not found or (keys and len(found) != len(keys)):
        raise UnresolvedReferenceError(
            f"{reference.document}: '{reference.passage}' names no passage that applies on {day}"
        )
    return found


def rule_passages(corpus: Corpus, rule_id: str, day: date) -> tuple[DatedPassage, ...]:
    """The passages the SRB-CIUS rule ``rule_id`` is authored from, on ``day``, each once."""
    rule = next((rule for rule in RULES if rule.id == rule_id), None)
    if rule is None:
        raise KeyError(rule_id)
    passages = (
        passage for reference in rule.references for passage in passages_for(corpus, reference, day)
    )
    return tuple({passage.id: passage for passage in passages}.values())
