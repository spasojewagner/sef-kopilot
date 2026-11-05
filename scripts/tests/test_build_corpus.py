"""Tests for scripts/build_corpus.py: reading each kind of source, downloading and checking the
sources, writing and checking the corpus."""

from __future__ import annotations

import hashlib
import io
import textwrap
import urllib.error
from pathlib import Path
from typing import Any

import pytest

import build_corpus
from build_corpus import (
    SourceError,
    _cells,
    _Columns,
    _Entry,
    _joined,
    _path_cell,
    _Section,
    _struck,
    _text_of,
    _Word,
    build,
    fetch,
    main,
    pis_html,
    tax_categories,
)
from sef_api.rag.corpus import Edition, Passage, load_corpus, load_manifest

REPOSITORY_CORPUS = build_corpus.CORPUS
needs_sources = pytest.mark.skipif(
    not (REPOSITORY_CORPUS / "raw").is_dir(),
    reason="the corpus's sources are not downloaded (make corpus)",
)


# --- consolidated texts of the Legal Information System ------------------------------------------

#: A consolidated text as the system serves one, with each thing the reader must leave out.
CONSOLIDATED = textwrap.dedent(
    """\
    ﻿<html xmlns="http://www.w3.org/1999/xhtml"><head><meta charset="utf-8" /></head><body>
    <p class="redakcijskipreciscentekst">Редакцијски пречишћен текст</p>
    <p class="odluka-zakon">ЗAКOН</p>
    <p class="auto-style1">"Службени гласник РС", бр. 44 од 29. априла 2021, 80 од 2026.</p>
    <p><em>НАПОМЕНА ИЗДАВАЧА: Закон ... ступа на снагу ...</em></p>
    <p class="clan">I. УВOДНE OДРEДБE</p>
    <p class="bold">Прeдмeт зaкoнa</p>
    <p class="clan">Члан 1.</p>
    <p class="Basic-Paragraph">Oвим зaкoнoм урeђуje сe
      <span class="v2-clan-left-1">издавање</span> фактура ;</p>
    <p class="hide-change"><em>2) брисана је (види члан 7. Закона - 92/2023-236)</em></p>
    <p class="Basic-Paragraph">3) трећа тачка (члан 3. ).</p>
    <p class="auto-style2"><span class="hide-change">*Службени гласник РС, број 94/2024</span></p>
    <p class="hide-change">**Службени гласник РС, број 92/2023</p>
    <p class="v2-clan-1">Члан 1a</p>
    <p class="Basic-Paragraph">Нови члан<!-- a comment --> са ознаком.</p>
    <p class="hide-change"><em>Члaн 2.</em></p>
    <p class="hide-change"><em>Брисан је (види члан 8. Закона - 109/2025-11)</em></p>
    <p><em>Члан 3.</em></p>
    <p><em>Брисан је (види члан 9. Закона - 109/2025-11)</em></p>
    <p class="clan">II. ЗАВРШНЕ ОДРЕДБЕ</p>
    <p><strong>Ступање на снагу</strong></p>
    <p><strong>Члан 4.</strong></p>
    <p>Овај закон ступа на снагу осмог дана.</p>
    <p class="potpis">Број 110-00-52/2023-41</p>
    <p class="auto-style2">У Београду, 28. маја 2003. године</p>
    <p class="auto-style2">Министар,</p>
    <p class="auto-style2"><strong>Синиша Мали</strong>, с.р.</p>
    <p class="bold">ОДРЕДБЕ КОЈЕ НИСУ УНЕТЕ У "ПРЕЧИШЋЕН ТЕКСТ" ЗАКОНА</p>
    <p class="italik">Закон о изменама Закона: "Службени гласник РС", број 80/2026-197</p>
    <p class="auto-style1"><strong>Члан 7.</strong></p>
    <p><strong>Овај закон примењиваће се од 1. јануара 2027. године.</strong></p>
    <p class="clan" style="text-align: right">Прилози</p>
    <p><a class="auto-style3" href="https://example.org/1.html">Образац ПР-1</a></p>
    </body></html>
    """
)


def test_a_consolidated_text_is_read_article_by_article() -> None:
    passages = pis_html(CONSOLIDATED.encode())

    assert passages == [
        Passage(
            key="Article 1",
            label="Члан 1.",
            heading="Предмет закона",
            part="I. УВОДНЕ ОДРЕДБЕ",
            amended_by=("92/2023", "94/2024"),
            text="Овим законом уређује се издавање фактура;\n\n3) трећа тачка (члан 3.).",
        ),
        Passage(
            key="Article 1a",
            label="Члан 1а.",
            text="Нови члан са ознаком.",
            part="I. УВОДНЕ ОДРЕДБЕ",
        ),
        Passage(
            key="Article 4",
            label="Члан 4.",
            heading="Ступање на снагу",
            part="II. ЗАВРШНЕ ОДРЕДБЕ",
            text="Овај закон ступа на снагу осмог дана.",
        ),
        Passage(
            key="80/2026, Article 7",
            label="Члан 7.",
            part='Закон о изменама Закона: "Службени гласник РС", број 80/2026-197',
            text="Овај закон примењиваће се од 1. јануара 2027. године.",
        ),
    ]


@pytest.mark.parametrize(
    ("body", "problem"),
    [
        ('<p class="clan">Члан 1.</p><p class="clan">Члан 1.</p>', "Article 1 has no text"),
        (
            '<p class="clan">Члан 1.</p><p>А.</p><p class="clan">Члан 1.</p><p>Б.</p>',
            "repeat the numbers Article 1",
        ),
        ('<p class="clan">I. ДЕО</p><p>Текст без члана.</p>', "text outside an article"),
        ('<p class="clan">Члан 1.</p><p class="bold">Наслов.</p>', "a heading that ends"),
        (
            '<p class="clan">Члан 1.</p><p>А.</p><p class="bold">Наслов</p><p>Б.</p>',
            "text outside an article",
        ),
    ],
)
def test_a_consolidated_text_that_cannot_be_read_is_refused(body: str, problem: str) -> None:
    with pytest.raises(SourceError, match=problem):
        pis_html(f"<html><body>{body}</body></html>".encode())


def test_a_page_without_a_body_is_refused() -> None:
    with pytest.raises(SourceError, match="without a body"):
        pis_html(b"<!-- nothing -->")


# --- the SRB-CIUS specification -------------------------------------------------------------------

COLUMNS = _Columns(term=96, cardinality=259, type=287, note=310)


def word(text: str, x0: float, y: float, **kind: bool) -> _Word:
    return _Word(
        text=text,
        x0=x0,
        x1=x0 + 6 * len(text),
        y=y,
        italic=kind.get("italic", False),
        courier=kind.get("courier", False),
        struck=kind.get("struck", False),
        columns=COLUMNS,
    )


def test_a_row_of_the_table_is_its_terms_cardinality_type_note_and_paths() -> None:
    words = [
        word("+", 96, 100),
        word("Seller", 105, 100, italic=True),
        word("electronic", 145, 100, italic=True),
        word("address", 116, 114, italic=True),
        word("електронска", 116, 128),
        word("адреса", 190, 128),
        word("0..1", 261, 99, struck=True),
        word("1..1", 261, 113),
        word("I", 294, 100),
        word("Користиће", 312, 100),
        word("се:", 380, 100),
        word("380", 312, 114),
        word("–", 336, 114),
        word("фактура", 348, 114),
        word("ПИБ-", 312, 128),
        word("а", 312, 142),
        word("/Invoice/cac:Party/cbc:Endpoin", 259, 150, courier=True),
        word("tID", 259, 159, courier=True),
        word("/CreditNote/cac:Party/cbc:EndpointID", 259, 168, courier=True),
        word("Напомена:", 259, 180),
        word("користити", 320, 180),
        word("„9948“", 259, 194),
    ]

    cells = _cells(words)

    assert cells.heading() == "Seller electronic address — електронска адреса"
    assert cells.text() == (
        "Кардиналност: 1..1 (у основном моделу фактуре: 0..1)\n\n"
        "Тип: I\n\n"
        "Додатна напомена о употреби: Користиће се:\n380 – фактура ПИБ-а\n\n"
        "UBL путања: /Invoice/cac:Party/cbc:EndpointID\n/CreditNote/cac:Party/cbc:EndpointID\n"
        "Напомена: користити „9948“"
    )


def test_a_line_across_the_columns_of_a_row_without_a_path_is_its_note() -> None:
    words = [
        word("+PRECEDING", 90, 100, italic=True),
        word("Ова", 259, 100),
        word("група", 285, 100),
        word("је", 320, 100),
        word("наведена.", 259, 114),
    ]

    assert _cells(words).text() == "Додатна напомена о употреби: Ова група је наведена."
    assert _cells(words).heading() == "PRECEDING"


def test_a_scheme_below_a_rows_path_is_a_row_it_nests() -> None:
    entry = _Entry("BT-29", 1, "Табела 1 Речник", start=100)
    entry.words = [
        word("Seller", 105, 100, italic=True),
        word("identifier", 145, 100, italic=True),
        word("0..n", 261, 100),
        word("/Invoice/cbc:ID", 259, 114, courier=True),
        word("Scheme", 116, 128, italic=True),
        word("identifier", 160, 128, italic=True),
        word("0..1", 261, 127),
        word("S", 294, 128),
        word("/Invoice/cbc:ID/@schemeID", 259, 142, courier=True),
    ]

    passage = entry.passage()

    assert passage.key == "1.3, Table 1, BT-29"
    assert passage.heading == "Seller identifier"
    assert passage.text == (
        "Кардиналност: 0..n\n\nUBL путања: /Invoice/cbc:ID\n\n"
        "Scheme identifier\n\nКардиналност: 0..1\n\nТип: S\n\n"
        "UBL путања: /Invoice/cbc:ID/@schemeID"
    )


def test_a_term_wrapped_beside_a_path_does_not_start_a_nested_row() -> None:
    entry = _Entry("BT-21", 1, "Табела 1", start=100)
    entry.words = [
        word("Invoice", 105, 100, italic=True),
        word("0..1", 261, 100),
        word("/Invoice/cbc:Note", 259, 112, courier=True),
        word("code", 116, 114, italic=True),
        word("шифра", 116, 128),
    ]

    assert len(entry.rows()) == 1
    assert entry.passage().heading == "Invoice code — шифра"


def test_a_value_is_struck_through_by_a_thin_rule_across_its_middle() -> None:
    value = {"x0": 260.0, "x1": 278.0, "top": 378.0, "bottom": 390.0}
    rule = {"x0": 259.0, "x1": 279.0, "top": 384.0, "height": 0.6}

    assert _struck(value, [rule])
    assert not _struck(value, [rule | {"height": 13.8}])  # a cell's border
    assert not _struck(value, [rule | {"top": 395.0}])


def test_words_split_where_the_font_changes_are_joined_again() -> None:
    words = [
        {"x0": 438.2, "x1": 478.5, "text": "BT-120,"},
        {"x0": 481.5, "x1": 489.5, "text": "B"},
        {"x0": 489.6, "x1": 496.9, "text": "Т"},
        {"x0": 496.9, "x1": 522.9, "text": "-121)"},
    ]

    assert _text_of(words) == "BT-120, BТ-121)"


def test_wrapped_lines_are_joined_where_the_break_fell() -> None:
    assert _joined(["urn:cen.eu:en16931:2017#conformant#", "urn:mfin.gov.rs"]) == (
        "urn:cen.eu:en16931:2017#conformant#urn:mfin.gov.rs"
    )
    assert _joined(["„RS-", "VAT-STATUS“", "и", "даље"]) == "„RS-VAT-STATUS“ и даље"
    assert _joined(["urn:mfin", ".gov.rs"]) == "urn:mfin.gov.rs"
    assert _path_cell(
        [
            (1, "/Invoice/cac:A/cac:Contact", True),
            (2, "/cbc:ElectronicMail", True),
            (3, "/CreditNote/cac:A", True),
            (0, "За продавца:", False),
        ]
    ) == ["За продавца:", "/Invoice/cac:A/cac:Contact/cbc:ElectronicMail", "/CreditNote/cac:A"]


def test_a_section_keeps_its_paragraphs_and_bullets() -> None:
    section = _Section("1.2", "Идентификација")
    section.lines = [
        (100.0, "Идентификација ове спецификације је:"),
        (123.0, "- urn:cen.eu:en16931:2017#compliant#"),
        (137.0, "urn:mfin.gov.rs:srbdt:2022 – ако се не"),
        (151.0, "примењује"),
        (175.0, "Напомињемо да"),
    ]

    assert section.passage().text == (
        "Идентификација ове спецификације је:\n\n"
        "- urn:cen.eu:en16931:2017#compliant#urn:mfin.gov.rs:srbdt:2022 – ако се не примењује\n\n"
        "Напомињемо да"
    )


@needs_sources
def test_the_specification_is_read_into_its_sections_and_its_two_tables() -> None:
    corpus = load_corpus(REPOSITORY_CORPUS)
    rows = {p.key: p for p in corpus.passages if p.document == "srb-cius"}

    assert [key for key in rows if "Table" not in key] == ["1.1", "1.2", "1.3", "1.4"]
    assert sum("Table 1," in key for key in rows) == 196
    assert sum("Table 2," in key for key in rows) == 34
    assert "Кардиналност: 0..0 (у основном моделу фактуре: 0..1)" in rows["1.3, Table 1, BT-7"].text
    assert "Наводи се „9948“" in rows["1.3, Table 1, BT-34"].text
    assert rows["1.3, Table 1, BT-65"].heading == "Tax representative address line 2 — ред 2 адресе"
    assert rows["1.3, Table 1, BG-31"].heading.startswith("ITEM INFORMATION")  # type: ignore[union-attr]


# --- the list of tax categories ------------------------------------------------------------------


def test_the_list_of_tax_categories_is_read_category_by_category() -> None:
    lines = [
        "Пореске категорије и шифре од 1. септембра 2024.",
        "Пореска категорија АЕ20 - Промет по стопи од 20% за који је порески дужник",
        "прималац:",
        "PDV-RS-10-2-1 - Промет секундарних сировина",
        "и услуга",
        "Page 1 of 11",
        "PDV-RS-36b-4 - ПДВ се не плаћа на:",
        "1) промет и увоз инвестиционог злата;",
        "2) промет услуга посредника",
        "Пореска категорија N – Анулирање једну од понуђених:",
        "PDV-RS-3-DZ - Умањење износа за плаћање.",
    ]

    assert tax_categories(lines) == [
        Passage(
            key="Tax category AE20",
            label="Пореска категорија AE20",
            heading="Промет по стопи од 20% за који је порески дужник прималац:",
            text="PDV-RS-10-2-1 - Промет секундарних сировина и услуга\n\n"
            "PDV-RS-36b-4 - ПДВ се не плаћа на:\n1) промет и увоз инвестиционог злата;\n"
            "2) промет услуга посредника",
        ),
        Passage(
            key="Tax category N",
            label="Пореска категорија N",
            heading="Анулирање једну од понуђених:",
            text="PDV-RS-3-DZ - Умањење износа за плаћање.",
        ),
    ]


def test_a_list_that_names_a_category_twice_or_without_codes_is_refused() -> None:
    category = "Пореска категорија N – Анулирање"
    with pytest.raises(SourceError, match="Tax category N twice"):
        tax_categories([category, "PDV-RS-4 - А", category, "PDV-RS-5 - Б"])
    with pytest.raises(SourceError, match="without a code or entries"):
        tax_categories([category])


# --- sources and editions ------------------------------------------------------------------------

SOURCE = CONSOLIDATED.encode()
DIGEST = hashlib.sha256(SOURCE).hexdigest()

MANIFEST = f"""\
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
source_url = "https://example.org/law.html"
source_file = "law.html"
sha256 = "{DIGEST}"
fetched_at = 2026-11-05
"""


class Response(io.BytesIO):
    def __enter__(self) -> Response:
        return self

    def __exit__(self, *exception: object) -> None:
        self.close()


def serving(data: bytes, requests: list[Any] | None = None) -> Any:
    def opener(request: Any, timeout: float) -> Response:
        del timeout
        if requests is not None:
            requests.append(request)
        return Response(data)

    return opener


def failing(request: Any, timeout: float) -> Response:
    del request, timeout
    raise urllib.error.URLError("no route to host")


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    (tmp_path / "manifest.toml").write_text(MANIFEST, encoding="utf-8")
    return tmp_path


def the_edition(corpus: Path) -> Edition:
    return load_manifest(corpus)[0].editions[0]


def test_a_source_is_downloaded_once_and_checked_against_its_digest(corpus: Path) -> None:
    requests: list[Any] = []

    assert fetch(the_edition(corpus), corpus / "raw", opener=serving(SOURCE, requests))
    assert not fetch(the_edition(corpus), corpus / "raw", opener=serving(SOURCE, requests))

    assert (corpus / "raw/law.html").read_bytes() == SOURCE
    assert [request.full_url for request in requests] == ["https://example.org/law.html"]


def test_a_source_that_changed_or_cannot_be_downloaded_is_not_kept(
    corpus: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(SourceError, match="if the publisher changed it"):
        fetch(the_edition(corpus), corpus / "raw", opener=serving(SOURCE + b" "))
    with pytest.raises(SourceError, match=r"cannot download .* no route to host"):
        fetch(the_edition(corpus), corpus / "raw", opener=failing)
    monkeypatch.setattr(build_corpus, "MAX_SOURCE_BYTES", 10)
    with pytest.raises(SourceError, match="larger than 10 bytes"):
        fetch(the_edition(corpus), corpus / "raw", opener=serving(SOURCE))

    assert not (corpus / "raw/law.html").exists()


def test_the_corpus_is_written_from_its_sources_and_checked_against_them(corpus: Path) -> None:
    assert build(corpus, corpus / "raw", check=False, download=True, opener=serving(SOURCE)) == []
    assert build(corpus, corpus / "raw", check=True, download=False) == []

    (passage, *_) = load_corpus(corpus).passages
    assert passage.id == "law/article-1/2026-04-01"
    (corpus / "law/2026-04-01.md").write_text("# Zakon\n", encoding="utf-8")
    assert build(corpus, corpus / "raw", check=True, download=False) == [
        "law/2026-04-01.md is not what its source makes; rebuild it"
    ]


def test_a_missing_or_changed_source_is_a_problem_to_report(corpus: Path) -> None:
    (problem,) = build(corpus, corpus / "raw", check=True, download=False)
    assert "law.html is missing; run with --fetch" in problem

    (corpus / "raw").mkdir()
    (corpus / "raw/law.html").write_bytes(SOURCE + b"\n")
    (problem,) = build(corpus, corpus / "raw", check=True, download=False)
    assert "is not the source the manifest names" in problem


def test_a_source_of_a_kind_without_a_reader_is_a_problem(corpus: Path) -> None:
    manifest = MANIFEST.replace('source_format = "pis-html"', 'source_format = "docx"')
    (corpus / "manifest.toml").write_text(manifest, encoding="utf-8")

    (problem,) = build(corpus, corpus / "raw", check=True, download=False)
    assert "no reader for a source of kind docx" in problem


def test_the_command_says_whether_the_corpus_is_what_its_sources_make(
    corpus: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (corpus / "raw").mkdir()
    (corpus / "raw/law.html").write_bytes(SOURCE)

    assert main(["--corpus", str(corpus), "--check"]) == 1
    assert main(["--corpus", str(corpus)]) == 0
    assert main(["--corpus", str(corpus), "--check"]) == 0

    out, err = capsys.readouterr()
    assert "wrote law/2026-04-01.md" in out
    assert "the corpus is what its sources make" in out
    assert "is not what its source makes" in err


def test_the_command_reports_a_manifest_it_cannot_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--corpus", str(tmp_path), "--check"]) == 1
    assert "manifest.toml" in capsys.readouterr().err


@needs_sources
def test_the_repositorys_corpus_is_what_its_sources_make() -> None:
    assert build(REPOSITORY_CORPUS, REPOSITORY_CORPUS / "raw", check=True, download=False) == []
