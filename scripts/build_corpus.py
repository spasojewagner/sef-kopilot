"""Write the corpus's editions from the official sources its manifest names.

The corpus (``corpus/``, ADR-0020) holds the text of the official documents that an explanation
may cite. ``corpus/manifest.toml`` names, for every edition of every document, the source it is
taken from: a URL and the SHA-256 digest of what that URL returned. This script downloads the
sources into ``corpus/raw/`` (which Git ignores), checks their digests, takes the text of each
passage out of them, and writes each edition's Markdown, ``corpus/<document>/<day>.md``. The
Markdown is committed; the sources are not.

It takes the text of the document as the document prints it, and nothing its publisher added:
the legal-information system's editorial notes, the marks of deleted items, the signatures
and the forms of a regulation are left out, and its footnotes on which issue of the Official
Gazette last amended an article become that article's ``amended-by``. Three kinds of source
are read:

* ``pis-html``: a consolidated text from the Legal Information System of the Republic of Serbia
  (``pravno-informacioni-sistem.rs``), one passage per article;
* ``srb-cius-pdf``: the SRB-CIUS specification, one passage per numbered section and one per
  row of its tables, struck-through cardinalities included;
* ``tax-categories-pdf``: the Ministry's list of tax categories and exemption codes, one passage
  per tax category.

Usage::

    uv run python scripts/build_corpus.py --fetch    # download the missing sources, then write
    uv run python scripts/build_corpus.py            # write corpus/ from corpus/raw/
    uv run python scripts/build_corpus.py --check    # fail if corpus/ is not what they make

A source whose digest is not the manifest's is an error: the publisher changed it, and the
change is reviewed, and the manifest updated, before the corpus is rebuilt.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import re
import sys
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final

import pdfplumber
from lxml import etree

from sef_api.rag.corpus import (
    CorpusError,
    Document,
    Edition,
    Passage,
    load_manifest,
    render_edition,
)
from sef_api.rag.text import (
    cyrillic_letters,
    cyrillic_text,
    cyrillic_words,
    latin_identifier,
    transliterate,
)

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[1]
CORPUS: Final = REPOSITORY_ROOT / "corpus"

MAX_SOURCE_BYTES: Final = 16 * 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS: Final = 60


class SourceError(Exception):
    """A source could not be fetched, verified or read; the message says which and why."""


_SPACE_BEFORE_MARK: Final = re.compile(r"(?<=\S) +(?=\)|[,.;:](?:\s|$))")


def _one_line(text: str) -> str:
    """``text`` on one line: its spaces collapsed, its soft hyphens dropped, and no space before
    a punctuation mark (the markup of an amended phrase leaves one: "фактура ;")."""
    return _SPACE_BEFORE_MARK.sub("", " ".join(text.replace("\xad", "").split()))


def _clean(text: str) -> str:
    """A line of a Serbian text in Cyrillic, its words put back into Cyrillic."""
    return cyrillic_text(_one_line(text))


def _glued(line: str, continuation: str) -> str:
    """A wrapped line and the line that continues it: no space where the break fell inside
    a word (``RS-`` and ``VAT-STATUS``, ``#conformant#`` and ``urn:…``, ``mfin`` and ``.gov``)."""
    inside = (
        line.endswith(("#", "/"))
        or re.search(r"\w-$", line) is not None
        or continuation.startswith((".", ",", ";", ":", ")"))
    )
    return f"{line}{'' if inside else ' '}{continuation}"


def _joined(lines: Iterable[str], *, breaks: re.Pattern[str] | None = None) -> str:
    """Lines of a wrapped cell or paragraph as one text: a line that ``breaks`` matches, or one
    after a colon, starts a line of its own; the others continue the line before."""
    out: list[str] = []
    for line in lines:
        starts = breaks is not None and breaks.match(line) is not None
        if out and not starts and not out[-1].endswith(":"):
            out[-1] = _glued(out[-1], line)
        else:
            out.append(line)
    return "\n".join(out)


def _repeated(passages: list[Passage]) -> list[str]:
    keys = [passage.key for passage in passages]
    return sorted({key for key in keys if keys.count(key) > 1})


# --- consolidated texts of the Legal Information System ------------------------------------------

_LETTERS: Final = "абвгдђежзијклљмнњопрстћуфхцчџш"
#: An article's label; its letter may be a Latin look-alike ("3a" for "3а").
_ARTICLE: Final = re.compile(rf"^Члан\s+(\d+)\s*([{_LETTERS}aceojpxy])?\s*\.?$")
_CHAPTER: Final = re.compile(r"^[IVXLC]+[АA]?\.?\s+\S")
_FOOTNOTE: Final = re.compile(r"^\*+\s*[„\"“]?Службени гласник РС[”\"]?,?\s+број\s+(\d+/\d{4})\.?$")
_AMENDING_ACT: Final = re.compile(r"^(?:Закон|Правилник|Уредба)\s.*\bброј\s+(\d+/\d{4})(?:-\d+)?$")
#: Where the system prints the final provisions of the amending acts.
_NOT_INCLUDED: Final = "ОДРЕДБЕ КОЈЕ НИСУ УНЕТЕ"
#: Where the forms begin, after the last provision.
_ANNEXES: Final = "Прилози"
_SIGNATURE: Final = re.compile(
    r"^(?:Број\s+\d{3}-\d{2}-\S+|У Београду,\s+\d.*|Министар(?: финансија)?,?|.*\bс\.р\.)$"
)
_EDITORIAL: Final = re.compile(
    r"^(?:НАПОМЕНА ИЗДАВАЧА\b|(?:\d+\)\s*)?брисан[аеио]?\s+(?:је|су)\b)", re.IGNORECASE
)
_HEADINGS: Final = frozenset({"bold", "v2-bold-1", "v2-bold-left-1"})
_CHAPTERS: Final = frozenset({"clan", "v2-clan-1"})
#: What the system shows only with the changes: footnotes, and the notes on deleted text.
_HIDDEN: Final = "hide-change"


def _classes(element: Any) -> set[str]:
    return set((element.get("class") or "").split())


def _shown_text(paragraph: Any) -> tuple[str, list[str]]:
    """The text of a paragraph without what the system hides with the changes, and the
    footnotes among what it hides (``*Службени гласник РС, број …``)."""
    shown: list[str] = []
    hidden: list[str] = []

    def walk(element: Any, hide: bool) -> None:
        hide = hide or _HIDDEN in _classes(element)
        into = hidden if hide else shown
        into.append(element.text or "")
        for child in element:
            if isinstance(child.tag, str):  # not a comment
                walk(child, hide)
            into.append(child.tail or "")

    walk(paragraph, False)
    notes = [_clean(note) for note in "".join(hidden).split("*")]
    return _clean("".join(shown)), [f"*{note}" for note in notes if note]


def _all_inside(paragraph: Any, inside: Callable[[Any], bool]) -> bool:
    """Whether every bit of the paragraph's text lies in an element for which ``inside`` holds."""

    def covered(element: Any, top: bool) -> bool:
        if not top and inside(element):
            return True
        if (element.text or "").strip():
            return False
        return all(
            (not isinstance(child.tag, str) or covered(child, False))
            and not (child.tail or "").strip()
            for child in element
        )

    return covered(paragraph, True)


def _issue_order(issue: str) -> tuple[int, int]:
    """Issues of the Official Gazette in the order they appeared: ``92/2023`` before ``94/2024``."""
    number, year = issue.split("/")
    return int(year), int(number)


@dataclass
class _Article:
    key: str
    label: str
    heading: str | None
    part: str | None
    paragraphs: list[str] = field(default_factory=list)
    amended_by: list[str] = field(default_factory=list)
    deleted: bool = False

    def passage(self) -> Passage:
        if not self.paragraphs:
            raise SourceError(f"{self.key} has no text")
        return Passage(
            key=self.key,
            label=self.label,
            text="\n\n".join(self.paragraphs),
            heading=self.heading,
            part=self.part,
            amended_by=tuple(sorted(set(self.amended_by), key=_issue_order)),
        )


@dataclass
class _PisReader:
    """Reads a consolidated text paragraph by paragraph, into articles."""

    articles: list[_Article] = field(default_factory=list)
    part: str | None = None
    heading: str | None = None
    #: The issue of the amending act whose final provisions are being read.
    amending: str | None = None
    started: bool = False
    final_provisions: bool = False

    def read(self, paragraphs: Iterable[Any]) -> list[Passage]:
        for paragraph in paragraphs:
            if not self._paragraph(paragraph):
                break
        passages = [article.passage() for article in self.articles if not article.deleted]
        if repeated := _repeated(passages):
            raise SourceError(f"articles repeat the numbers {', '.join(repeated)}")
        return passages

    def _paragraph(self, paragraph: Any) -> bool:
        """Take one paragraph in; False where the provisions end."""
        classes = _classes(paragraph)
        text, notes = _shown_text(paragraph)
        for note in notes:
            if (match := _FOOTNOTE.match(note)) and self.articles:
                self.articles[-1].amended_by.append(match.group(1))
        if not text or "potpis" in classes or _SIGNATURE.match(text):
            return True
        if text == _ANNEXES:
            return False
        if _EDITORIAL.match(text) and _all_inside(paragraph, lambda element: element.tag == "em"):
            if self.articles and not self.articles[-1].paragraphs:  # stands for a deleted article
                self.articles[-1].deleted = True
        elif not self._structure(text, classes):
            self._text(paragraph, classes, text)
        return True

    def _structure(self, text: str, classes: set[str]) -> bool:
        """Whether the paragraph marks the structure: a part, an amending act, an article."""
        if text.startswith(_NOT_INCLUDED):
            self.final_provisions, self.part, self.heading = True, None, None
        elif self.final_provisions and (match := _AMENDING_ACT.match(text)):
            self.amending, self.part, self.heading = match.group(1), text, None
        elif classes & _CHAPTERS and _CHAPTER.match(text):
            self.started, self.part, self.heading = True, text, None
        elif match := _ARTICLE.match(text):
            self.started = True
            number = match.group(1) + cyrillic_letters(match.group(2) or "")
            key = f"Article {transliterate(number)}"
            article = _Article(
                key=key if self.amending is None else f"{self.amending}, {key}",
                label=f"Члан {number}.",
                heading=self.heading,
                part=self.part,
            )
            self.articles.append(article)
            self.heading = None
        else:
            return False
        return True

    def _text(self, paragraph: Any, classes: set[str], text: str) -> None:
        if not self.started:
            return  # the title, the Gazette's issues, the preamble
        if not self.final_provisions and _is_heading(paragraph, classes, text):
            self.heading = text
        elif not self.articles or self.heading is not None:
            raise SourceError(f"text outside an article: {text[:80]!r}")
        else:
            self.articles[-1].paragraphs.append(text)


def _is_heading(paragraph: Any, classes: set[str], text: str) -> bool:
    """Whether a paragraph is the heading of the article that follows."""
    if classes & _HEADINGS:
        if text.endswith("."):
            raise SourceError(f"a heading that ends a sentence: {text[:80]!r}")
        return True
    emphasised = _all_inside(
        paragraph, lambda element: element.tag == "strong" or bool(_classes(element) & _HEADINGS)
    )
    return emphasised and not classes - {"Basic-Paragraph"} and not text.endswith(tuple(".:;,"))


def pis_html(data: bytes) -> list[Passage]:
    """The articles of a consolidated text of the Legal Information System, and the final
    provisions of its amending acts, which the system prints after them."""
    root = etree.HTML(data.decode("utf-8-sig"), etree.HTMLParser(no_network=True))
    body = None if root is None else root.find("body")
    if body is None:
        raise SourceError("an HTML page without a body")
    return _PisReader().read(body.iter("p"))


# --- the SRB-CIUS specification -------------------------------------------------------------------

_SECTION: Final = re.compile(r"^(\d+\.\d+)\.\s+(\S.*)$")
_CAPTION: Final = re.compile(r"^Табела\s+(\d+)\s+(\S.*)$")
_TERM: Final = re.compile(r"^[BВ][GTТ]-[EЕ]?\d+$")
_TERMS_IN_TEXT: Final = re.compile(r"\b[BВ][GTТ]-[EЕ]?\d+\b")
_CARDINALITY: Final = re.compile(r"^\d\.\.[\dn]$")
_PAGE_NUMBER: Final = re.compile(r"^\d+$")
_BULLET: Final = re.compile(r"^(?:-|o)\s")
_LIST_ITEM: Final = re.compile(r"^(?:\d+\s+[–-]\s|[-o•]\s)")
#: Where a UBL path begins: at the document's root, or at one of the extension's (the paths of
#: Table 2 are relative to it). Any other line continues the path a narrow column wrapped.
_PATH_START: Final = re.compile(
    r"^(?:/(?:Invoice|CreditNote)(?:/|$)|(?:InvoicedPrepaymentAmmount|ReducedTotals)(?:/|$))"
)
#: The section that holds each table.
_SECTION_TABLES: Final = {1: "1.3", 2: "1.4"}

#: How far apart the pages are put, so that a position orders words across pages.
_PAGE: Final = 10_000
#: Points within which two words stand on one line.
_SAME_LINE: Final = 3
#: The most points between two lines of one paragraph.
_PARAGRAPH_GAP: Final = 18
#: The thickest rule that strikes a value through, in points (a cell's border is thicker).
_RULE: Final = 1.5
#: Below this, on a page, stands its number.
_FOOTER_TOP: Final = 760

#: Rows whose identifier the specification misprints: (page, printed identifier, how many
#: times it was printed before on that page) and the identifier the row has.
SPECIFICATION_ERRATA: Final = {
    # The row after BT-64 "Tax representative address line 1" is EN 16931's BT-65 "Tax
    # representative address line 2"; the specification prints BT-64 twice.
    (11, "BT-64", 1): "BT-65",
    # BG-31 ITEM INFORMATION, the group of the item's name and description, is printed BT-31,
    # the identifier of the seller's VAT number (which page 6 holds).
    (20, "BT-31", 0): "BG-31",
}


@dataclass(frozen=True)
class _Columns:
    """Where the columns of a page's table begin, from its header."""

    term: float
    cardinality: float
    type: float
    note: float


@dataclass(frozen=True)
class _Word:
    text: str
    x0: float
    x1: float
    #: The page's number times :data:`_PAGE`, plus the word's top on the page.
    y: float
    italic: bool
    courier: bool
    struck: bool
    #: The columns of the word's page.
    columns: _Columns


def _share(word: dict[str, Any], font: str) -> float:
    """How much of the word is set in a font whose name has ``font`` in it."""
    chars = word["chars"]
    return sum(font in char["fontname"] for char in chars) / len(chars)


def _struck(word: dict[str, Any], rects: list[dict[str, Any]]) -> bool:
    """Whether a thin rule runs through the middle of the word: a struck-through value."""
    middle = (word["top"] + word["bottom"]) / 2
    return any(
        rect["height"] < _RULE
        and rect["x0"] <= word["x0"] + 1
        and rect["x1"] >= word["x1"] - 1
        and abs(rect["top"] - middle) < _SAME_LINE
        for rect in rects
    )


def _lines(words: Iterable[_Word]) -> list[list[_Word]]:
    """Words in lines, top to bottom, each line left to right."""
    lines: list[list[_Word]] = []
    for word in sorted(words, key=lambda word: (word.y, word.x0)):
        if lines and abs(lines[-1][0].y - word.y) < _SAME_LINE:
            lines[-1].append(word)
        else:
            lines.append([word])
    return [sorted(line, key=lambda word: word.x0) for line in lines]


def _text_of(words: Iterable[_Word | dict[str, Any]]) -> str:
    """The words of a line as text, with a space only where the page leaves a gap: pdfplumber
    splits a word where its font changes, as "BТ-121" with a Cyrillic "Т" is split."""
    out = ""
    previous: float | None = None
    for word in words:
        if isinstance(word, _Word):
            x0, x1, text = word.x0, word.x1, word.text
        else:
            x0, x1, text = word["x0"], word["x1"], word["text"]
        out += text if previous is not None and x0 - previous < 1 else f" {text}"
        previous = x1
    return out.strip()


def _spec_text(text: str) -> str:
    """A line of the specification: its Cyrillic words in Cyrillic, its term identifiers in
    Latin letters (the specification also writes BТ-121 with a Cyrillic Т)."""
    return _TERMS_IN_TEXT.sub(
        lambda match: latin_identifier(match.group()), cyrillic_words(_one_line(text))
    )


def _by_column(line: list[_Word]) -> dict[str, list[_Word]]:
    out: dict[str, list[_Word]] = {}
    for word in line:
        columns = word.columns
        if word.x0 < columns.term - 3 and _TERM.match(word.text):
            column = "id"
        elif word.x0 < columns.cardinality - 2:
            column = "term"  # a level's plus signs may stand left of the header
        elif word.x0 < columns.type:
            column = "cardinality"
        elif word.x0 < columns.note:
            column = "type"
        else:
            column = "note"
        out.setdefault(column, []).append(word)
    return out


@dataclass
class _Cells:
    """What one row of a table says, column by column."""

    english: list[str] = field(default_factory=list)
    serbian: list[str] = field(default_factory=list)
    values: list[str] = field(default_factory=list)
    struck: list[str] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    #: The lines of the UBL path's cell: where each is, its text, and whether it is a path.
    paths: list[tuple[float, str, bool]] = field(default_factory=list)

    def add(self, column: str, words: list[_Word]) -> None:
        if column == "term":
            terms = [replace(word, text=word.text.lstrip("+")) for word in words]
            if english := [word for word in terms if word.text and word.italic]:
                self.english.append(_text_of(english))
            if serbian := [word for word in terms if word.text and not word.italic]:
                self.serbian.append(_text_of(serbian))
        elif column == "cardinality":
            for word in words:
                (self.struck if word.struck else self.values).append(word.text)
        elif column == "type":
            self.kinds.append(_text_of(words))
        elif column == "note":
            self.notes.append(_text_of(words))

    def heading(self) -> str:
        terms = (" ".join(self.english), _spec_text(" ".join(self.serbian)))
        return " — ".join(term for term in terms if term)

    def text(self) -> str:
        text = []
        if self.values:
            core = f" (у основном моделу фактуре: {', '.join(self.struck)})" if self.struck else ""
            text.append(f"Кардиналност: {', '.join(self.values)}{core}")
        if self.kinds:
            text.append(f"Тип: {latin_identifier(' '.join(self.kinds))}")
        if self.notes:
            note = _joined((_spec_text(line) for line in self.notes), breaks=_LIST_ITEM)
            text.append(f"Додатна напомена о употреби: {note}")
        if self.paths:
            text.append("UBL путања: " + "\n".join(_path_cell(self.paths)))
        return "\n\n".join(text)


def _path_cell(lines: list[tuple[float, str, bool]]) -> list[str]:
    """The lines of a UBL path's cell, top to bottom: paths, each joined from the narrow lines
    it was wrapped into, and the notes among them, each joined likewise."""
    out: list[str] = []
    previous: bool | None = None
    for _, text, is_path in sorted(lines):
        if is_path and previous is True and not _PATH_START.match(text):
            out[-1] += text
        elif not is_path and previous is False and not out[-1].endswith(":"):
            out[-1] = _glued(out[-1], _spec_text(text))
        else:
            out.append(text if is_path else _spec_text(text))
        previous = is_path
    return out


def _cells(words: list[_Word]) -> _Cells:
    """The cells of one row from its words.

    A line may run across the columns from where the UBL path stands: it belongs to the path's
    cell, in its place among the paths ("for the payee:" before the payee's paths, a note after
    them), or, in a row without a path, it is the row's note.
    """
    cells = _Cells()
    cells.paths = [
        (line[0].y, "".join(word.text for word in line), True)
        for line in _lines(word for word in words if word.courier)
    ]
    has_paths = bool(cells.paths)
    for line in _lines(word for word in words if not word.courier):
        by_column = _by_column(line)
        wide = next(
            (
                word
                for word in by_column.get("cardinality", [])
                if not _CARDINALITY.match(word.text)
            ),
            None,
        )
        if wide is not None:
            text = _text_of(word for word in line if word.x0 >= wide.x0)
            if has_paths:
                cells.paths.append((line[0].y, text, False))
            else:
                cells.notes.append(text)
            by_column = _by_column([word for word in line if word.x0 < wide.x0])
        for column, column_words in by_column.items():
            cells.add(column, column_words)
    return cells


@dataclass
class _Entry:
    """A row of a table with an identifier, and the rows it nests."""

    id: str
    table: int
    caption: str
    #: Where the row's identifier is.
    start: float
    words: list[_Word] = field(default_factory=list)

    def rows(self) -> list[list[_Word]]:
        """The row and the rows it nests: a line below the row's UBL path that names a term
        and its cardinality (an identifier's scheme, say) starts a nested row."""
        rows: list[list[_Word]] = [[]]
        below_path = False
        for line in _lines(self.words):
            columns = _by_column([word for word in line if not word.courier])
            starts = "term" in columns and any(
                _CARDINALITY.match(word.text) for word in columns.get("cardinality", [])
            )
            if below_path and starts:
                rows.append([])
                below_path = False
            rows[-1] += line
            below_path = below_path or any(word.courier for word in line)
        return rows

    def passage(self) -> Passage:
        main, *nested = (_cells(row) for row in self.rows())
        text = main.text()
        for row in nested:
            text += f"\n\n{row.heading()}\n\n{row.text()}"
        return Passage(
            key=f"{_SECTION_TABLES[self.table]}, Table {self.table}, {self.id}",
            label=self.id,
            text=text,
            heading=main.heading() or None,
            part=self.caption,
        )


@dataclass
class _Section:
    number: str
    title: str
    #: Its lines: where each stands, and its text.
    lines: list[tuple[float, str]] = field(default_factory=list)

    def passage(self) -> Passage:
        paragraphs: list[list[str]] = []
        previous: float | None = None
        for top, text in self.lines:
            gap = None if previous is None or top < previous else top - previous
            if not paragraphs or _BULLET.match(text) or (gap is not None and gap > _PARAGRAPH_GAP):
                paragraphs.append([text])
            else:
                paragraphs[-1].append(text)
            previous = top
        return Passage(
            key=self.number,
            label=f"{self.number}.",
            text="\n\n".join(_joined(lines) for lines in paragraphs),
            heading=self.title,
        )


def _page_columns(words: list[dict[str, Any]]) -> _Columns:
    """The columns of a page's table, from the words of its header: a type stands a little
    left of its header, a note right under its own."""
    named = {word["text"]: word for word in words}
    try:
        return _Columns(
            term=named["Ниво,"]["x0"] if "Ниво," in named else named["Ниво"]["x0"],
            cardinality=named["UBL"]["x0"],
            type=named["Т"]["x0"] - 6,
            note=named["Додатна"]["x0"] - 2,
        )
    except KeyError:
        raise SourceError("a table without its header") from None


def _in_any(word: dict[str, Any], boxes: list[tuple[float, float, float, float]]) -> bool:
    return any(
        box[0] <= word["x0"] and word["x1"] <= box[2] and box[1] <= word["top"] <= box[3]
        for box in boxes
    )


def _plain_lines(words: list[dict[str, Any]]) -> Iterator[tuple[float, str, bool]]:
    """Text outside the tables as lines: where each stands, its text, and whether it is bold."""
    lines: list[list[dict[str, Any]]] = []
    for word in sorted(words, key=lambda word: (word["top"], word["x0"])):
        if lines and abs(lines[-1][0]["top"] - word["top"]) < _SAME_LINE:
            lines[-1].append(word)
        else:
            lines.append([word])
    for line in lines:
        line.sort(key=lambda word: word["x0"])
        bold = all(_share(word, "Bold") == 1 for word in line)
        yield line[0]["top"], _text_of(line), bold


@dataclass
class _SpecReader:
    """Reads the specification page by page, into sections and table rows."""

    sections: list[_Section] = field(default_factory=list)
    entries: list[_Entry] = field(default_factory=list)
    table: int = 0
    caption: str = ""
    #: How many times each identifier was printed on each page so far.
    printed: dict[tuple[int, str], int] = field(default_factory=dict)

    def page(self, number: int, page: Any) -> None:
        boxes = [found.bbox for found in page.find_tables()]
        words = page.extract_words(return_chars=True)
        self._text(word for word in words if not _in_any(word, boxes))
        inside = [word for word in words if _in_any(word, boxes)]
        if inside:
            try:
                self._table(number, page, inside, boxes[0][1])
            except SourceError as error:
                raise SourceError(f"page {number}: {error}") from None

    def _text(self, words: Iterable[dict[str, Any]]) -> None:
        for top, text, bold in _plain_lines(list(words)):
            if _PAGE_NUMBER.match(text) and top > _FOOTER_TOP:
                continue
            if bold and (match := _SECTION.match(text)):
                self.sections.append(_Section(match.group(1), _spec_text(match.group(2))))
            elif match := _CAPTION.match(text):
                self.table, self.caption = int(match.group(1)), _spec_text(text)
            elif self.sections:
                self.sections[-1].lines.append((top, _spec_text(text)))

    def _table(self, number: int, page: Any, inside: list[dict[str, Any]], top: float) -> None:
        """Hand the words of a page's table to the rows they belong to: a row begins at its
        identifier, and the words above the first identifier of a page go on the row before."""
        columns = _page_columns([word for word in inside if word["top"] < top + 30])
        header_end = max(word["top"] for word in inside if word["text"] == "путања") + 5
        words = [
            _Word(
                text=word["text"],
                x0=word["x0"],
                x1=word["x1"],
                y=number * _PAGE + word["top"],
                italic=_share(word, "Italic") > 0.5,  # noqa: PLR2004  # mostly italic
                courier=_share(word, "Courier") > 0,
                struck=_struck(word, page.rects),
                columns=columns,
            )
            for word in sorted(inside, key=lambda word: (word["top"], word["x0"]))
            if word["top"] >= header_end
        ]
        starts = [word for word in words if word.x0 < columns.term - 3 and _TERM.match(word.text)]
        for start in starts:
            seen = self.printed.get((number, start.text), 0)
            self.printed[(number, start.text)] = seen + 1
            identifier = SPECIFICATION_ERRATA.get(
                (number, start.text, seen), latin_identifier(start.text)
            )
            self.entries.append(_Entry(identifier, self.table, self.caption, start.y))
        for word in words:
            if word in starts:
                continue
            owners = [entry for entry in self.entries if entry.start - _SAME_LINE <= word.y]
            if not owners:
                raise SourceError("a table row without an identifier")
            owners[-1].words.append(word)


def srb_cius_pdf(data: bytes) -> list[Passage]:
    """The numbered sections of the SRB-CIUS specification and the rows of its tables."""
    reader = _SpecReader()
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            reader.page(number, page)
    passages = [section.passage() for section in reader.sections]
    passages += [entry.passage() for entry in reader.entries]
    if repeated := _repeated(passages):
        raise SourceError(f"rows repeat the identifiers of {', '.join(repeated)}")
    return passages


# --- the list of tax categories ------------------------------------------------------------------

_CATEGORY: Final = re.compile(r"^Пореска категорија\s+(\S+)\s+[-–]\s*(\S.*)$")
_EXEMPTION: Final = re.compile(r"^PDV-RS-\S")
_ITEM: Final = re.compile(r"^\d+\)\s")
_FOOTER: Final = re.compile(r"^Page \d+ of \d+$")


@dataclass
class _Category:
    header: list[str]
    entries: list[list[str]] = field(default_factory=list)

    def passage(self) -> Passage:
        match = _CATEGORY.match(" ".join(self.header))
        if match is None or not self.entries:
            raise SourceError(f"a tax category without a code or entries: {self.header[0]!r}")
        code = latin_identifier(match.group(1))
        return Passage(
            key=f"Tax category {code}",
            label=f"Пореска категорија {code}",
            text="\n\n".join("\n".join(entry) for entry in self.entries),
            heading=match.group(2),
        )


def tax_categories(lines: Iterable[str]) -> list[Passage]:
    """The tax categories of the Ministry's list, from its lines: each category's header, then
    its exemption codes, each with what it is for (and the items of that, if it has any)."""
    categories: list[_Category] = []
    for line in lines:
        if _FOOTER.match(line):
            continue
        if line.startswith("Пореска категорија"):
            categories.append(_Category([line]))
        elif not categories:
            continue  # the list's title
        elif _EXEMPTION.match(line):
            categories[-1].entries.append([line])
        elif not categories[-1].entries:
            categories[-1].header.append(line)  # a header that wraps
        elif _ITEM.match(line):
            categories[-1].entries[-1].append(line)
        else:
            entry = categories[-1].entries[-1]
            entry[-1] = _glued(entry[-1], line)
    passages = [category.passage() for category in categories]
    if repeated := _repeated(passages):
        raise SourceError(f"the list names {', '.join(repeated)} twice")
    return passages


def tax_categories_pdf(data: bytes) -> list[Passage]:
    """The tax categories of the Ministry's list (a PDF), each with its exemption codes."""
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        lines = [
            _clean(text)
            for page in pdf.pages
            for _, text, _ in _plain_lines(page.extract_words(return_chars=True))
        ]
    return tax_categories(lines)


# --- sources and editions ------------------------------------------------------------------------

#: How each kind of source is read.
FORMATS: Final[dict[str, Callable[[bytes], list[Passage]]]] = {
    "pis-html": pis_html,
    "srb-cius-pdf": srb_cius_pdf,
    "tax-categories-pdf": tax_categories_pdf,
}

Opener = Callable[..., Any]


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _changed(where: str, digest: str) -> SourceError:
    return SourceError(
        f"{where} is not the source the manifest names (its SHA-256 is {digest}): if the "
        "publisher changed it, review the change and update the manifest"
    )


def source(edition: Edition, raw: Path) -> bytes:
    """The edition's source from ``raw``, checked against the manifest's digest."""
    path = raw / edition.source_file
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        raise SourceError(f"{path} is missing; run with --fetch") from None
    if (digest := _digest(data)) != edition.sha256:
        raise _changed(str(path), digest)
    return data


def fetch(edition: Edition, raw: Path, *, opener: Opener = urllib.request.urlopen) -> bool:
    """Download the edition's source into ``raw`` unless it is there; whether it did."""
    target = raw / edition.source_file
    if target.exists():
        return False
    request = urllib.request.Request(edition.source_url, headers={"User-Agent": "sef-kopilot"})
    try:
        with opener(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
            data = response.read(MAX_SOURCE_BYTES + 1)
    except (urllib.error.URLError, TimeoutError) as error:
        raise SourceError(f"cannot download {edition.source_url}: {error}") from None
    if len(data) > MAX_SOURCE_BYTES:
        raise SourceError(f"{edition.source_url} is larger than {MAX_SOURCE_BYTES} bytes")
    if (digest := _digest(data)) != edition.sha256:
        raise _changed(edition.source_url, digest)
    raw.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=raw, delete=False) as out:
        out.write(data)
    Path(out.name).replace(target)
    return True


def edition_markdown(document: Document, edition: Edition, raw: Path) -> str:
    """The Markdown of an edition, made from its source."""
    read = FORMATS.get(document.source_format)
    if read is None:
        raise SourceError(
            f"{document.key}: no reader for a source of kind {document.source_format}"
        )
    try:
        return render_edition(document.title, read(source(edition, raw)))
    except (SourceError, CorpusError) as error:
        raise SourceError(f"{edition.file}: {error}") from None


def build(
    corpus: Path, raw: Path, *, check: bool, download: bool, opener: Opener = urllib.request.urlopen
) -> list[str]:
    """Write (or, with ``check``, compare) every edition's Markdown; the problems found."""
    problems: list[str] = []
    for document in load_manifest(corpus):
        for edition in document.editions:
            try:
                if download and fetch(edition, raw, opener=opener):
                    print(f"fetched {edition.source_file}")
                markdown = edition_markdown(document, edition, raw)
            except SourceError as error:
                problems.append(str(error))
                continue
            target = corpus / edition.file
            written = target.read_text(encoding="utf-8") if target.exists() else None
            if written == markdown:
                continue
            if check:
                problems.append(f"{edition.file} is not what its source makes; rebuild it")
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                # LF on every platform, as Git keeps the file: the same bytes on Windows too.
                target.write_text(markdown, encoding="utf-8", newline="\n")
                print(f"wrote {edition.file}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--fetch", action="store_true", help="download the missing sources")
    parser.add_argument(
        "--check", action="store_true", help="compare corpus/ with its sources, write nothing"
    )
    parser.add_argument("--corpus", type=Path, default=CORPUS, help=argparse.SUPPRESS)
    arguments = parser.parse_args(argv)
    corpus: Path = arguments.corpus
    try:
        problems = build(corpus, corpus / "raw", check=arguments.check, download=arguments.fetch)
    except CorpusError as error:
        problems = [str(error)]
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if not problems:
        print("the corpus is what its sources make" if arguments.check else "the corpus is built")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
