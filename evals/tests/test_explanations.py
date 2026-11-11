"""The explanations' evaluations: the golden set, the rules explained, and their citations."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text

from sef_api.db import Database
from sef_api.rag.explainer import Citation, Explanation
from sef_evals.database import DatabaseError, corpus_database, server_url
from sef_evals.explanations import (
    Asked,
    ExplanationGolden,
    Labels,
    explain,
    load_golden,
    measure,
    unlabelled,
)
from sef_evals.golden import GoldenError

from .conftest import REPOSITORY_ROOT, SERVER, Explaining, needs_database

PIB = "fixtures/invoices/synthetic/mutations/srb-009-pib-check-digit.xml"
SELLER = "fixtures/invoices/synthetic/mutations/br-06-seller-name.xml"
ARTICLE_2 = "pib-rulebook/article-2/2018-10-01"
BT_27 = "srb-cius/1-3-table-1-bt-27/2025-06-06"
BT_28 = "srb-cius/1-3-table-1-bt-28/2025-06-06"
DAY = date(2026, 11, 9)


def golden(**rules: Labels) -> ExplanationGolden:
    return ExplanationGolden(day=DAY, languages=("sr",), documents=(PIB, SELLER), rules=dict(rules))


@pytest.fixture
async def database() -> AsyncIterator[Database]:
    assert SERVER is not None
    async with corpus_database(SERVER, REPOSITORY_ROOT / "corpus", "sef_evals_test") as made:
        yield made


def test_the_repository_golden_set_is_labelled_one_way_per_passage() -> None:
    loaded = load_golden(REPOSITORY_ROOT / "evals" / "golden" / "explanations.yaml")
    assert loaded.languages == ("sr",)
    assert len(loaded.paths(REPOSITORY_ROOT)) == 41
    assert ARTICLE_2 in loaded.rules["SRB-009"].relevant
    assert not any("/xml-" in path for path in loaded.paths(REPOSITORY_ROOT))


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        (
            "day: 2026-11-09\nlanguages: [sr]\ndocuments: [d.xml]\nrules:\n"
            "  SRB-009: {relevant: [a], not_relevant: [a]}\n",
            "SRB-009: a labelled both ways",
        ),
        ("day: 2026-11-09\nlanguages: [de]\ndocuments: [d.xml]\nrules: {}\n", "languages"),
        ("day: 2026-11-09\nlanguages: []\ndocuments: [d.xml]\nrules: {}\n", "languages"),
        ("day: someday\nlanguages: [sr]\ndocuments: [d.xml]\nrules: {}\n", "day"),
        ("day: 2026-11-09\nlanguages: [sr]\ndocuments: [d.xml]\nrules: {}\nmodel: x\n", "model"),
        ("day: [\n", "explanations.yaml"),
    ],
)
def test_refuses_a_golden_set_it_cannot_trust(tmp_path: Path, text: str, problem: str) -> None:
    path = tmp_path / "explanations.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(GoldenError, match=problem):
        load_golden(path)


def test_names_the_documents_without_those_excluded(tmp_path: Path) -> None:
    for name in ("a.xml", "b.xml", "xml-c.xml"):
        (tmp_path / name).write_text("<Invoice/>", encoding="utf-8")
    some = ExplanationGolden(
        day=DAY, languages=("sr",), documents=("*.xml", "a.xml"), exclude=("xml-*.xml",), rules={}
    )
    assert some.paths(tmp_path) == ["a.xml", "b.xml"]
    nowhere = some.model_copy(update={"exclude": ("z*.xml",)})
    with pytest.raises(GoldenError, match=r"'z\*\.xml' names no document"):
        nowhere.paths(tmp_path)


def test_needs_a_database_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEF_TEST_DATABASE_URL", raising=False)
    with pytest.raises(DatabaseError, match="SEF_TEST_DATABASE_URL is not set"):
        server_url(tmp_path / ".env")
    (tmp_path / ".env").write_text("SEF_TEST_DATABASE_URL=postgresql+asyncpg://x@y/z\n")
    assert server_url(tmp_path / ".env") == "postgresql+asyncpg://x@y/z"


@pytest.mark.parametrize("value", ["", "  "])
def test_an_empty_database_server_is_one_not_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    # As .env.example leaves it, and as the API's tests read it: empty is not set.
    monkeypatch.delenv("SEF_TEST_DATABASE_URL", raising=False)
    (tmp_path / ".env").write_text(f"SEF_TEST_DATABASE_URL={value}\n")
    with pytest.raises(DatabaseError, match="SEF_TEST_DATABASE_URL is not set"):
        server_url(tmp_path / ".env")
    monkeypatch.setenv("SEF_TEST_DATABASE_URL", value)
    with pytest.raises(DatabaseError, match="SEF_TEST_DATABASE_URL is not set"):
        server_url(tmp_path / ".env")


def test_a_database_server_that_is_no_url_is_refused_without_repeating_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SEF_TEST_DATABASE_URL", '"not-a-real-password@localhost"')
    with pytest.raises(DatabaseError) as refused:
        server_url(tmp_path / ".env")
    message = str(refused.value)
    assert message.startswith("SEF_TEST_DATABASE_URL is not a database URL")
    assert "postgresql+asyncpg://user:password@localhost:5432/postgres" in message
    assert "not-a-real-password" not in message


async def test_a_server_that_is_not_running_is_named_without_its_password(
    tmp_path: Path,
) -> None:
    # Nothing listens on port 9 of this machine (the discard service is never enabled).
    stopped = "postgresql+asyncpg://sef:not-a-real-password@127.0.0.1:9/postgres"
    with pytest.raises(DatabaseError) as refused:
        async with corpus_database(stopped, tmp_path):
            pass  # pragma: no cover - never reached
    message = str(refused.value)
    assert message.startswith("the PostgreSQL server at 127.0.0.1:9 cannot be reached (")
    assert "up -d db" in message
    assert "not-a-real-password" not in message


@needs_database
async def test_the_database_holds_the_corpus_and_is_dropped_after() -> None:
    assert SERVER is not None
    async with corpus_database(SERVER, REPOSITORY_ROOT / "corpus", "sef_evals_test") as made:
        async with made.sessions() as session:
            stored = await session.scalar(text("SELECT count(*) FROM corpus_passages"))
        assert stored is not None
        assert stored > 100
    async with Database.connect(SERVER, pooled=False).sessions() as session:
        left = await session.scalar(
            text("SELECT count(*) FROM pg_database WHERE datname = 'sef_evals_test'")
        )
    assert left == 0


@needs_database
async def test_explains_every_rule_and_measures_the_citations(database: Database) -> None:
    labelled = golden(**{"SRB-009": Labels(relevant=frozenset({ARTICLE_2})), "BR-06": Labels()})
    asked = await explain(REPOSITORY_ROOT, labelled, database, Explaining(), progress=None)
    assert [(a.document, a.language, a.explanation.rule_id) for a in asked] == [
        (PIB, "sr", "SRB-009"),
        (SELLER, "sr", "BR-06"),
    ]
    assert [c.id for a in asked for c in a.explanation.citations] == [ARTICLE_2, BT_27]
    measures = {m.name: m for m in await measure(labelled, database, asked)}
    assert (measures["explained"].total, measures["explained"].failures) == (2, ())
    assert (measures["citation_resolution"].total, measures["citation_resolution"].value) == (
        2,
        1,
    )
    assert measures["citation_relevance"].failures == (
        f"{SELLER} [sr] BR-06: cites {BT_27}, which no label names",
    )
    relabelled = golden(
        **{
            "SRB-009": Labels(relevant=frozenset({ARTICLE_2})),
            "BR-06": Labels(not_relevant=frozenset({BT_27})),
        }
    )
    relevance = (await measure(relabelled, database, asked))[2]
    assert relevance.failures == (f"{SELLER} [sr] BR-06: cites {BT_27}, labelled not relevant",)
    assert relevance.value == 0.5


@needs_database
async def test_tells_the_progress_and_names_what_the_model_did_not_explain(
    database: Database,
) -> None:
    told: list[str] = []
    model = Explaining("Groq answered 503, 3 times")
    asked = await explain(REPOSITORY_ROOT, golden(), database, model, progress=told.append)
    assert told == [f"the rules of {PIB} [sr]", f"the rules of {SELLER} [sr]"]
    explained = (await measure(golden(), database, asked))[0]
    assert explained.failures == (
        f"{PIB} [sr] SRB-009: the model gave no answer (Groq answered 503, 3 times)",
    )
    assert explained.value == 0.5


@needs_database
async def test_a_citation_resolves_only_to_a_stored_passage_that_applies(
    database: Database,
) -> None:
    def cited(passage: str, valid_from: date) -> Asked:
        citation = Citation(
            id=passage,
            document="pib-rulebook",
            title="Pravilnik",
            label="Član 2.",
            heading=None,
            version="2018-10-01",
            valid_from=valid_from,
            valid_to=None,
            source_url="https://example.invalid/",
        )
        explanation = Explanation(
            rule_id="SRB-009", violations=1, text="t", fix="f", citations=(citation,)
        )
        return Asked(PIB, "sr", explanation)

    asked = [cited(ARTICLE_2, date(2018, 10, 1)), cited("pib-rulebook/article-99/2018-10-01", DAY)]
    resolution = (await measure(golden(), database, asked))[1]
    assert resolution.failures == (
        f"{PIB} [sr] SRB-009: cites pib-rulebook/article-99/2018-10-01, not stored",
    )
    # On a day before the rulebook applied, the passage it cites does not apply.
    earlier = golden().model_copy(update={"day": date(2018, 1, 1)})
    assert (await measure(earlier, database, asked[:1]))[1].failures == (
        f"{PIB} [sr] SRB-009: cites {ARTICLE_2}, not stored",
    )
    nothing = await measure(golden(), database, [])
    assert [m.total for m in nothing] == [0, 0, 0]


@needs_database
async def test_lists_the_passages_retrieval_finds_that_no_label_names(database: Database) -> None:
    labelled = golden(**{"BR-06": Labels(relevant=frozenset({BT_27}))})
    found = await unlabelled(REPOSITORY_ROOT, labelled, database)
    assert list(found) == ["BR-06", "SRB-009"]
    assert BT_27 not in [p.id for p in found["BR-06"]]
    assert BT_28 in [p.id for p in found["BR-06"]]
    assert found["SRB-009"][0].id == ARTICLE_2
