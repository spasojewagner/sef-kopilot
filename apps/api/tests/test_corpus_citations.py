"""Citations: every reference of every SRB-CIUS rule resolves to passages of the corpus, on every
day the corpus covers, and the documents the rules cite are the corpus's documents."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from einvoice_core.srb import RULES, SOURCES, Reference
from sef_api.rag import citations
from sef_api.rag.citations import (
    UnresolvedReferenceError,
    keys_of,
    passages_for,
    rule_passages,
)
from sef_api.rag.corpus import Corpus, load_corpus
from sef_api.rag.text import transliterate

CORPUS = Path(__file__).resolve().parents[3] / "corpus"
TODAY = date(2026, 11, 5)


@pytest.fixture(scope="module")
def corpus() -> Corpus:
    return load_corpus(CORPUS)


def test_a_reference_names_one_passage_rows_of_a_table_or_a_whole_list() -> None:
    assert keys_of(Reference("srb-cius", "1.2")) == ("1.2",)
    assert keys_of(Reference("pib-rulebook", "Article 2")) == ("Article 2",)
    assert keys_of(Reference("srb-cius", "1.3, Table 1, BT-3")) == ("1.3, Table 1, BT-3",)
    assert keys_of(Reference("srb-cius", "1.3, Table 1, BT-95, BT-102, BT-151")) == (
        "1.3, Table 1, BT-95",
        "1.3, Table 1, BT-102",
        "1.3, Table 1, BT-151",
    )
    assert keys_of(Reference("tax-categories", "the list for each tax category")) == ()


@pytest.mark.parametrize(
    "day", [date(2025, 6, 6), TODAY, date(2027, 1, 1), date(2027, 7, 1), date(2030, 1, 1)]
)
def test_every_reference_of_every_rule_resolves_on_every_day_the_corpus_covers(
    corpus: Corpus, day: date
) -> None:
    for rule in RULES:
        for reference in rule.references:
            passages = passages_for(corpus, reference, day)
            assert passages, (rule.id, reference)
            assert all(passage.applies_on(day) for passage in passages)
            assert {passage.document for passage in passages} == {reference.document}


def test_a_rule_cites_each_passage_it_comes_from_once(
    corpus: Corpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    pib = rule_passages(corpus, "SRB-009", TODAY)
    tax = rule_passages(corpus, "SRB-023", TODAY)

    assert [passage.id for passage in pib] == [
        "pib-rulebook/article-2/2018-10-01",
        "srb-cius/1-3-table-1-bt-31/2025-06-06",
        "srb-cius/1-3-table-1-bt-34/2025-06-06",
    ]
    assert "МОДУЛ (11,10)" in pib[0].text
    assert len(tax) == 12  # the eleven tax categories and the specification's BT-121
    with pytest.raises(KeyError):
        rule_passages(corpus, "SRB-999", TODAY)

    twice = tuple(replace(rule, references=rule.references * 2) for rule in RULES)
    monkeypatch.setattr(citations, "RULES", twice)
    assert rule_passages(corpus, "SRB-009", TODAY) == pib  # named twice, cited once


def test_a_reference_to_a_passage_the_corpus_does_not_hold_is_an_error(corpus: Corpus) -> None:
    with pytest.raises(UnresolvedReferenceError, match=r"'1\.3, Table 1, BT-999' names no"):
        passages_for(corpus, Reference("srb-cius", "1.3, Table 1, BT-999"), TODAY)
    with pytest.raises(UnresolvedReferenceError):
        passages_for(corpus, Reference("srb-cius", "1.3, Table 1, BT-3, BT-999"), TODAY)
    with pytest.raises(UnresolvedReferenceError, match="applies on 2024-01-01"):
        passages_for(corpus, Reference("srb-cius", "1.2"), date(2024, 1, 1))
    with pytest.raises(UnresolvedReferenceError):
        passages_for(
            corpus, Reference("tax-categories", "the list for each tax category"), date(2024, 1, 1)
        )


def test_the_documents_the_rules_cite_are_the_corpus_s_documents(corpus: Corpus) -> None:
    for key, source in SOURCES.items():
        document = corpus.document(key)
        assert transliterate(document.title) == source.title
        assert document.publisher == source.publisher
        assert source.version in [edition.version for edition in document.editions], (
            f"the rules cite {key} {source.version}: review them against the corpus's editions"
        )
        if source.url is not None:
            assert document.page == source.url
