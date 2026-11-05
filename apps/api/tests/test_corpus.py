"""The corpus: Serbian text in two scripts, the edition files, the passages over time, the
manifest, and the corpus of the repository itself."""

from __future__ import annotations

import itertools
import textwrap
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sef_api.rag.corpus import (
    Corpus,
    CorpusError,
    DatedPassage,
    Deferral,
    Document,
    Edition,
    Passage,
    load_corpus,
    load_manifest,
    parse_edition,
    passage_id,
    render_edition,
)
from sef_api.rag.text import (
    cyrillic_letters,
    cyrillic_text,
    cyrillic_words,
    fold,
    latin_identifier,
    transliterate,
)

REPOSITORY_CORPUS = Path(__file__).resolve().parents[3] / "corpus"


# --- text in two scripts ------------------------------------------------------------------------


def test_cyrillic_is_written_in_serbian_latin_letter_for_letter() -> None:
    assert transliterate("Члан 4б. Шифра, ЉУБАВ, Џак, ђак, њива") == (
        "Član 4b. Šifra, LjUBAV, Džak, đak, njiva"
    )


@pytest.mark.parametrize(
    ("text", "folded"),
    [
        ("Шифра врсте фактуре", "sifra vrste fakture"),
        ("šifra  vrste\nfakture", "sifra vrste fakture"),
        ("ПДВ-а", "pdv-a"),
        ("Ђорђе, đak", "djordje, djak"),
        ("Члан 28ђ", "clan 28dj"),
    ],
)
def test_a_search_finds_a_text_in_either_script_and_without_diacritics(
    text: str, folded: str
) -> None:
    assert fold(text) == folded


def test_latin_look_alikes_inside_cyrillic_words_are_made_cyrillic() -> None:
    mixed = "Члaн 19. УВOДНE OДРEДБE"  # Latin "a", "O" and "E" among the Cyrillic letters

    assert cyrillic_words(mixed) == "Члан 19. УВОДНЕ ОДРЕДБЕ"
    assert cyrillic_words("UBL cbc:ID PDF") == "UBL cbc:ID PDF"


def test_a_cyrillic_text_also_gets_its_words_spelt_in_latin_look_alikes_back() -> None:
    assert cyrillic_text("Издавалац je дужан, a o томе") == "Издавалац је дужан, а о томе"
    assert cyrillic_text("члана 4a ст. 1") == "члана 4а ст. 1"
    # words with other Latin letters, and codes in capitals, stay as they are
    assert cyrillic_text("путем e-mail адресе, PDV-RS-OBJ, S20 и X.") == (
        "путем e-mail адресе, PDV-RS-OBJ, S20 и X."
    )


def test_identifiers_are_put_back_into_latin_letters() -> None:
    assert latin_identifier("BG-Е1, BТ-121, АЕ20") == "BG-E1, BT-121, AE20"
    assert cyrillic_letters("4a") == "4а"


# --- the edition files --------------------------------------------------------------------------

ARTICLE = Passage(
    key="Article 4b",
    label="Члан 4б.",
    heading="Електронско евидентирање набавке од пољопривредника",
    part="I. УВОДНЕ ОДРЕДБЕ",
    amended_by=("109/2025", "80/2026"),
    text="Први став.\n\n1) прва тачка;\n2) друга тачка.",
)
ROW = Passage(key="1.3, Table 1, BT-3", label="BT-3", text="Кардиналност: 1..1")

EDITION = textwrap.dedent(
    """\
    # Zakon o elektronskom fakturisanju

    ## Article 4b

    - label: Члан 4б.
    - heading: Електронско евидентирање набавке од пољопривредника
    - part: I. УВОДНЕ ОДРЕДБЕ
    - amended-by: 109/2025, 80/2026

    Први став.

    1) прва тачка;
    2) друга тачка.

    ## 1.3, Table 1, BT-3

    - label: BT-3

    Кардиналност: 1..1
    """
)


def test_an_edition_is_written_in_a_fixed_form_and_read_back() -> None:
    assert render_edition("Zakon o elektronskom fakturisanju", [ARTICLE, ROW]) == EDITION
    assert parse_edition(EDITION) == ("Zakon o elektronskom fakturisanju", (ARTICLE, ROW))


_LINE = (
    st.text(
        alphabet=st.sampled_from("абвгдђежзијклљмнњопрстћуфхцчџшABCabc0123456789.,;:()–- "),
        min_size=1,
        max_size=40,
    )
    .map(str.strip)
    .filter(bool)
    .filter(lambda line: not line.startswith(("#", "-")))
)
_PARAGRAPH = st.lists(_LINE, min_size=1, max_size=3).map("\n".join)
_PASSAGE = st.builds(
    Passage,
    key=_LINE,
    label=_LINE,
    text=st.lists(_PARAGRAPH, min_size=1, max_size=3).map("\n\n".join),
    heading=st.none() | _LINE,
    part=st.none() | _LINE,
    amended_by=st.lists(st.from_regex(r"\A[1-9][0-9]{0,2}/20[0-9]{2}\Z"), max_size=3).map(tuple),
)


@given(st.lists(_PASSAGE, min_size=1, max_size=4, unique_by=lambda passage: passage.key))
def test_any_edition_reads_back_as_it_was_written(passages: list[Passage]) -> None:
    assert parse_edition(render_edition("Наслов", passages)) == ("Наслов", tuple(passages))


@pytest.mark.parametrize(
    ("markdown", "problem"),
    [
        ("Zakon\n\n## A\n\n- label: L\n\nT\n", "must start with '# <title>'"),
        ("# Zakon\nprvi red\n", "must start with '# <title>'"),
        ("# Zakon\n", "an edition without passages"),
        ("# Zakon\n\nuvod\n\n## A\n\n- label: L\n\nT\n", "text before the first passage"),
        ("# Zakon\n\n## A\n- label: L\n\nT\n", "an empty line must follow '## A'"),
        ("# Zakon\n\n## A\n\n- heading: H\n\nT\n", "needs a label, then an empty line"),
        ("# Zakon\n\n## A\n\n- label: L\nT\n", "needs a label, then an empty line"),
        ("# Zakon\n\n## A\n\n- label: L\n- label: M\n\nT\n", "'label' is not one of"),
        ("# Zakon\n\n## A\n\n- note: N\n- label: L\n\nT\n", "'note' is not one of"),
        ("# Zakon\n\n## A\n\n- label: L\n\nT\n\n## A\n\n- label: L\n\nT\n", "repeat the keys A"),
        ("# Zakon\n\n## A\n\n- label: L\n\nT\n\n\nU\n", "its text must be paragraphs"),
        ("# Zakon\n\n## A\n\n- label: L\n\nT \n", "its text must be paragraphs"),
        ("# Zakon\n\n## A\n\n- label:  L\n\nT\n", "label must be one line"),
        ("# Zakon\n\n## A\n\n- label: L\n\nT", "not as scripts/build_corpus.py writes it"),
        ("# Zakon\n\n## A\n\n- label: L\n\nT\n\n", "not as scripts/build_corpus.py writes it"),
        ("# Zakon\n\n\n## A\n\n- label: L\n\nT\n", "not as scripts/build_corpus.py writes it"),
    ],
)
def test_an_edition_not_as_the_converter_writes_it_is_refused(markdown: str, problem: str) -> None:
    with pytest.raises(CorpusError, match=problem):
        parse_edition(markdown, where="e.md")


@pytest.mark.parametrize(
    "passage",
    [
        replace(ROW, key="1.3\nBT-3"),
        replace(ROW, label=" BT-3"),
        replace(ROW, text=""),
        replace(ROW, text="# a heading inside the text"),
        replace(ROW, text="one\n\n\nthree"),
    ],
)
def test_a_passage_that_the_form_cannot_hold_is_not_written(passage: Passage) -> None:
    with pytest.raises(CorpusError):
        render_edition("Naslov", [passage])


# --- the passages over time ---------------------------------------------------------------------


def edition(day: date, *passages: Passage, **changes: object) -> Edition:
    made = Edition(
        file=f"law/{day.isoformat()}.md",
        valid_from=day,
        version=f"version of {day.isoformat()}",
        source_url=f"https://example.org/{day.isoformat()}",
        source_file=f"{day.isoformat()}.html",
        sha256="0" * 64,
        fetched_at=date(2026, 11, 5),
        passages=passages,
    )
    return replace(made, **changes)  # type: ignore[arg-type]


def article(key: str, text: str) -> Passage:
    return Passage(key=key, label=key.replace("Article", "Члан") + ".", text=text)


def dated(*editions: Edition) -> list[tuple[str, str, date, date | None, date | None]]:
    document = Document(
        key="law",
        title="Zakon",
        kind="law",
        publisher="Narodna skupština",
        language="sr-Cyrl",
        page="https://example.org",
        source_format="pis-html",
        editions=editions,
    )
    return sorted(
        (p.key, p.text, p.valid_from, p.valid_to, p.fully_from)
        for p in Corpus((document,)).passages
    )


APRIL = date(2026, 4, 1)
JANUARY = date(2027, 1, 1)
JULY = date(2027, 7, 1)


def test_a_passage_a_later_edition_repeats_goes_on_and_a_changed_one_is_replaced() -> None:
    first = edition(APRIL, article("Article 1", "same"), article("Article 2", "old"))
    second = edition(JANUARY, article("Article 1", "same"), article("Article 2", "new"))

    assert dated(first, second) == [
        ("Article 1", "same", APRIL, None, None),
        ("Article 2", "new", JANUARY, None, None),
        ("Article 2", "old", APRIL, JANUARY, None),
    ]


@pytest.mark.parametrize(
    "changed",
    [
        Passage(key="Article 1", label="Члан 1а.", text="same"),
        Passage(key="Article 1", label="Члан 1.", heading="Предмет", text="same"),
        Passage(key="Article 1", label="Члан 1.", part="I. ДЕО", text="same"),
    ],
    ids=["label", "heading", "part"],
)
def test_a_passage_whose_label_heading_or_part_changes_is_replaced_too(changed: Passage) -> None:
    first = edition(APRIL, article("Article 1", "same"))
    second = edition(JANUARY, changed)

    assert dated(first, second) == [
        ("Article 1", "same", APRIL, JANUARY, None),
        ("Article 1", "same", JANUARY, None, None),
    ]


def test_a_passage_a_later_edition_drops_ends_when_that_edition_applies() -> None:
    first = edition(APRIL, article("Article 1", "kept"), article("Article 20", "deleted later"))
    second = edition(JANUARY, article("Article 1", "kept"))

    assert ("Article 20", "deleted later", APRIL, JANUARY, None) in dated(first, second)


def test_a_deferred_change_leaves_the_earlier_wording_in_force_until_it_applies() -> None:
    first = edition(APRIL, article("Article 2", "old"))
    second = edition(
        JANUARY,
        article("Article 2", "new"),
        article("Article 4b", "farmers"),
        deferred=(Deferral(("Article 2", "Article 4b"), JULY),),
    )

    assert dated(first, second) == [
        ("Article 2", "new", JULY, None, None),
        ("Article 2", "old", APRIL, JULY, None),
        ("Article 4b", "farmers", JULY, None, None),
    ]


def test_a_partly_deferred_passage_applies_at_once_and_says_when_all_of_it_does() -> None:
    first = edition(APRIL, article("Article 18", "old"))
    second = edition(
        JANUARY,
        article("Article 18", "new"),
        deferred=(Deferral(("Article 18",), JULY, partly=True),),
    )

    assert dated(first, second) == [
        ("Article 18", "new", JANUARY, None, JULY),
        ("Article 18", "old", APRIL, JANUARY, None),
    ]


def test_a_number_given_to_another_passage_ends_the_earlier_one_with_the_edition() -> None:
    # The rulebook's Article 29 becomes Article 30; the new Article 29 applies later.
    first = edition(APRIL, article("Article 29", "interruption"))
    second = edition(
        JANUARY,
        article("Article 29", "preliminary return"),
        article("Article 30", "interruption"),
        renumbered={"Article 29": "Article 30"},
        deferred=(Deferral(("Article 29",), JULY),),
    )

    assert dated(first, second) == [
        ("Article 29", "interruption", APRIL, JANUARY, None),
        ("Article 29", "preliminary return", JULY, None, None),
        ("Article 30", "interruption", JANUARY, None, None),
    ]


def test_ids_name_the_document_the_passage_and_the_day_it_began_to_apply() -> None:
    assert passage_id("e-invoicing-law", "Article 4b", JULY) == (
        "e-invoicing-law/article-4b/2027-07-01"
    )
    assert passage_id("e-invoicing-rulebook", "Article 28đ", JANUARY) == (
        "e-invoicing-rulebook/article-28dj/2027-01-01"
    )
    assert passage_id("srb-cius", "1.3, Table 1, BT-3", APRIL) == (
        "srb-cius/1-3-table-1-bt-3/2026-04-01"
    )
    assert passage_id("e-invoicing-law", "80/2026, Article 7", JANUARY) == (
        "e-invoicing-law/80-2026-article-7/2027-01-01"
    )


def test_a_passage_applies_from_its_first_day_up_to_but_not_on_its_last() -> None:
    first = edition(APRIL, article("Article 1", "old"))
    second = edition(JANUARY, article("Article 1", "new"))
    document = Document("law", "Zakon", "law", "P", "sr-Cyrl", "u", "pis-html", (first, second))
    corpus = Corpus((document,))

    old = corpus.passage("law", "Article 1", date(2026, 12, 31))
    new = corpus.passage("law", "Article 1", JANUARY)

    assert old is not None
    assert old.text == "old"
    assert not old.applies_on(JANUARY)
    assert new is not None
    assert new.text == "new"
    assert corpus.passage("law", "Article 1", date(2026, 3, 31)) is None
    assert [passage.text for passage in corpus.on(JANUARY)] == ["new"]
    with pytest.raises(KeyError):
        corpus.document("rulebook")


def test_what_a_search_compares_and_what_an_embedding_depends_on() -> None:
    passage = DatedPassage(
        id="law/article-1/2026-04-01",
        document="law",
        key="Article 1",
        label="Члан 1.",
        text="Шифра врсте фактуре",
        heading="Предмет",
        part=None,
        amended_by=(),
        valid_from=APRIL,
        valid_to=None,
        fully_from=None,
        version="v",
        source_url="u",
    )

    assert passage.search_text == "clan 1. predmet sifra vrste fakture"
    assert passage.text_sha256 != replace(passage, heading="Друго").text_sha256
    assert passage.text_sha256 == replace(passage, version="w").text_sha256


# --- the manifest -------------------------------------------------------------------------------

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
source_url = "https://example.org/1"
source_file = "law-1.html"
sha256 = "{sha}"
fetched_at = 2026-11-05

[[documents.editions]]
file = "law/2027-01-01.md"
valid_from = 2027-01-01
version = "1/2026 i 2/2026"
source_url = "https://example.org/2"
source_file = "law-2.html"
sha256 = "{sha}"
fetched_at = 2026-11-05
renumbered = {{ "Article 4b" = "Article 4v" }}

[[documents.editions.deferred]]
passages = ["Article 4b"]
valid_from = 2027-07-01

[[documents.editions.deferred]]
passages = ["Article 4v"]
valid_from = 2027-07-01
partly = true
"""


def write_corpus(directory: Path, manifest: str = MANIFEST) -> Path:
    (directory / "law").mkdir()
    (directory / "manifest.toml").write_text(manifest.format(sha="a" * 64), encoding="utf-8")
    first = [article("Article 1", "first"), article("Article 4b", "imports")]
    second = [*first[:1], article("Article 4b", "farmers"), article("Article 4v", "lists")]
    (directory / "law/2026-04-01.md").write_text(render_edition("Zakon", first), "utf-8")
    (directory / "law/2027-01-01.md").write_text(render_edition("Zakon", second), "utf-8")
    return directory


def test_the_corpus_is_its_manifest_and_its_edition_files(tmp_path: Path) -> None:
    corpus = load_corpus(write_corpus(tmp_path))

    (document,) = corpus.documents
    assert [edition.valid_from for edition in document.editions] == [APRIL, JANUARY]
    assert document.editions[1].renumbered == {"Article 4b": "Article 4v"}
    assert sorted((p.id, p.valid_to, p.fully_from) for p in corpus.passages) == [
        ("law/article-1/2026-04-01", None, None),
        ("law/article-4b/2026-04-01", JANUARY, None),
        ("law/article-4b/2027-07-01", None, None),
        ("law/article-4v/2027-01-01", None, JULY),
    ]
    assert load_manifest(tmp_path)[0].editions[0].passages == ()


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (('kind = "law"', 'kind = "treaty"'), "'kind' must be one of"),
        (('title = "Zakon"\n', ""), "'title' must be a str"),
        (("valid_from = 2026-04-01", 'valid_from = "2026-04-01"'), "'valid_from' must be a date"),
        (("valid_from = 2026-04-01", "valid_from = 2026-04-01T00:00:00"), "must be a date"),
        (("valid_from = 2027-01-01", "valid_from = 2026-01-01"), "oldest first"),
        (('sha256 = "{sha}"', 'sha256 = "ABC"'), "64 lowercase hexadecimal"),
        (
            (
                'passages = ["Article 4b"]\nvalid_from = 2027-07-01',
                'passages = ["Article 4b"]\nvalid_from = 2026-12-01',
            ),
            "a later day",
        ),
        (('passages = ["Article 4v"]', 'passages = ["Article 4b"]'), "deferred once at most"),
        (("partly = true", 'partly = "yes"'), "'partly' must be true or false"),
        (('passages = ["Article 4b"]', 'passages = ["Article 9"]'), "it does not have: Article 9"),
        (('"Article 4b" = "Article 4v"', '"Article 9" = "Article 4v"'), "'renumbered' must map"),
        (
            ('{{ "Article 4b" = "Article 4v" }}', '{{ "Article 4b" = 4 }}'),
            "'renumbered' must map keys",
        ),
        (
            ("[[documents.editions]]\nfile", "editions = 1\n[[documents.editions]]\nfile"),
            "TOMLDecodeError|Cannot",
        ),
    ],
)
def test_a_manifest_that_is_not_as_it_must_be_is_refused(
    tmp_path: Path, change: tuple[str, str], problem: str
) -> None:
    old, new = change
    assert old in MANIFEST
    with pytest.raises(CorpusError, match=problem):
        load_corpus(write_corpus(tmp_path, MANIFEST.replace(old, new, 1)))


def test_a_manifest_without_documents_or_with_one_twice_is_refused(tmp_path: Path) -> None:
    (tmp_path / "manifest.toml").write_text("documents = []\n", encoding="utf-8")
    with pytest.raises(CorpusError, match="each key once"):
        load_manifest(tmp_path)

    (tmp_path / "manifest.toml").write_text("documents = 5\n", encoding="utf-8")
    with pytest.raises(CorpusError, match="'documents' must be a list of tables"):
        load_manifest(tmp_path)

    (tmp_path / "manifest.toml").write_text(MANIFEST.format(sha="a" * 64) * 2, encoding="utf-8")
    with pytest.raises(CorpusError):
        load_manifest(tmp_path)


def test_the_first_edition_cannot_renumber_anything(tmp_path: Path) -> None:
    manifest = MANIFEST.replace(
        'source_file = "law-1.html"',
        'source_file = "law-1.html"\nrenumbered = {{ "Article 1" = "Article 1" }}',
    )
    with pytest.raises(CorpusError, match="the first cannot renumber"):
        load_corpus(write_corpus(tmp_path, manifest))


def test_an_edition_file_that_is_missing_or_has_another_title_is_refused(tmp_path: Path) -> None:
    write_corpus(tmp_path)
    (tmp_path / "law/2027-01-01.md").write_text(
        render_edition("Pravilnik", [article("Article 1", "first")]), encoding="utf-8"
    )
    with pytest.raises(CorpusError, match="the title must be 'Zakon'"):
        load_corpus(tmp_path)

    (tmp_path / "law/2027-01-01.md").unlink()
    with pytest.raises(CorpusError, match=r"2027-01-01\.md"):
        load_corpus(tmp_path)


def test_a_missing_manifest_is_refused(tmp_path: Path) -> None:
    with pytest.raises(CorpusError, match=r"manifest\.toml"):
        load_manifest(tmp_path)


# --- the corpus of the repository ---------------------------------------------------------------


@pytest.fixture(scope="module")
def corpus() -> Corpus:
    return load_corpus(REPOSITORY_CORPUS)


def test_the_repository_holds_the_five_documents_of_the_corpus(corpus: Corpus) -> None:
    assert [document.key for document in corpus.documents] == [
        "e-invoicing-law",
        "e-invoicing-rulebook",
        "pib-rulebook",
        "srb-cius",
        "tax-categories",
    ]
    assert all(passage.text and passage.label for passage in corpus.passages)


def test_no_two_passages_of_a_key_apply_on_the_same_day(corpus: Corpus) -> None:
    ids = [passage.id for passage in corpus.passages]
    assert len(set(ids)) == len(ids)
    by_key: dict[tuple[str, str], list[DatedPassage]] = {}
    for passage in corpus.passages:
        by_key.setdefault((passage.document, passage.key), []).append(passage)
    for passages in by_key.values():
        ordered = sorted(passages, key=lambda passage: passage.valid_from)
        for earlier, later in itertools.pairwise(ordered):
            assert earlier.valid_to is not None
            assert earlier.valid_to <= later.valid_from


def test_the_laws_changes_of_2027_apply_when_its_amending_act_says(corpus: Corpus) -> None:
    def on(day: date, key: str) -> DatedPassage | None:
        return corpus.passage("e-invoicing-law", key, day)

    november, march, august = date(2026, 11, 5), date(2027, 3, 1), date(2027, 8, 1)
    farmers = "пољопривредника"
    imports = on(november, "Article 4b")
    assert imports is not None
    assert farmers not in imports.text
    assert on(march, "Article 4b") is None  # the farmers' recording is not applied yet
    recording = on(august, "Article 4b")
    assert recording is not None
    assert farmers in recording.text
    lists = on(march, "Article 4v")
    assert lists is not None
    assert lists.fully_from == date(2027, 7, 1)
    definitions = on(march, "Article 2")
    assert definitions is not None
    assert definitions.valid_to == date(2027, 7, 1)
