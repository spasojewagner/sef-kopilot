"""The corpus: the official documents an explanation may cite, passage by passage, each passage
with the days between which it applies (ADR-0020).

``corpus/manifest.toml`` lists the documents and the editions of each. An edition is the text of
a document as consolidated at one point: the file it is kept in, the source it was taken from
(by URL and SHA-256 digest) and the day it applies from. It may also say that some of its
passages apply from a later day than the rest, as a law does when its final provisions defer
some of its changes, and which passages of the edition before it took a new number.

An edition's file is Markdown of a fixed form, written by ``scripts/build_corpus.py`` from the
official source and never by hand::

    # Zakon o elektronskom fakturisanju

    ## Article 4b

    - label: Члан 4б.
    - heading: Електронско евидентирање набавке од пољопривредника
    - part: I. УВОДНЕ ОДРЕДБЕ
    - amended-by: 80/2026

    Обавезу електронског евидентирања набавке ...

    Електронско евидентирање набавке од пољопривредника ...

A passage starts at a level-two heading, which is its key; the list under it says what the
document prints around the text (only the label is required), and the paragraphs after the list
are the text. Keys are identifiers in English ("Article 4b", "1.3, Table 1, BT-3"), the way the
validator's rules cite passages; labels, headings and texts are as the document prints them.

**Over time.** A passage applies from the day its edition applies, or the later day the edition
defers it to, until the day a later edition changes it, drops it or gives its number to another
passage. A passage that a later edition repeats exactly goes on, so its id, which names the day
it began to apply, stays the same as long as its text does. A passage whose wording changed
but whose change is deferred goes on in its earlier wording until the change applies. The first
edition of a document is where the corpus begins: its passages apply from that edition's day as
far as the corpus can tell, though their wording may be older.
"""

from __future__ import annotations

import hashlib
import re
import tomllib
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any, Final, Literal

from sef_api.rag.text import fold

__all__ = [
    "MANIFEST",
    "METADATA",
    "Corpus",
    "CorpusError",
    "DatedPassage",
    "Deferral",
    "Document",
    "Edition",
    "Passage",
    "load_corpus",
    "load_manifest",
    "parse_edition",
    "passage_id",
    "render_edition",
]

#: The manifest's name in the corpus directory.
MANIFEST: Final = "manifest.toml"

Kind = Literal["law", "rulebook", "specification", "list"]
_KINDS: Final[tuple[Kind, ...]] = ("law", "rulebook", "specification", "list")

#: What a passage may say besides its text, in the order it is written.
METADATA: Final = ("label", "heading", "part", "amended-by")

_SHA256: Final = re.compile(r"^[0-9a-f]{64}$")
#: A key, a label, a heading or a part: one line, no space at either end.
_LINE: Final = re.compile(r"^\S(?:[^\n]*\S)?$")


class CorpusError(Exception):
    """The corpus is not as it must be; the message says where."""


@dataclass(frozen=True)
class Passage:
    """A passage of one edition: an article, a section of a specification, a row of one of its
    tables, or an entry of a list."""

    key: str
    label: str
    text: str
    heading: str | None = None
    part: str | None = None
    #: The Official Gazette issues that gave the passage its present wording, oldest first.
    amended_by: tuple[str, ...] = ()


@dataclass(frozen=True)
class Deferral:
    """Passages of an edition that apply from a later day than the rest of it.

    When ``partly`` is set, the passages apply from the edition's day and only some of their
    provisions from ``valid_from``: an article whose change mixes provisions that apply at once
    with provisions that wait.
    """

    passages: tuple[str, ...]
    valid_from: date
    partly: bool = False


@dataclass(frozen=True)
class Edition:
    """A document as consolidated at one point, and where it was taken from."""

    file: str
    valid_from: date
    version: str
    source_url: str
    source_file: str
    sha256: str
    fetched_at: date
    deferred: tuple[Deferral, ...] = ()
    #: Keys of the edition before this one, each with the key its passage has in this one.
    renumbered: Mapping[str, str] = field(default_factory=dict)
    passages: tuple[Passage, ...] = ()

    def starts(self, key: str) -> date:
        """The day this edition's passage ``key`` applies from."""
        for deferral in self.deferred:
            if key in deferral.passages and not deferral.partly:
                return deferral.valid_from
        return self.valid_from

    def fully(self, key: str) -> date | None:
        """The day all of this edition's passage ``key`` applies, when part of it waits."""
        for deferral in self.deferred:
            if key in deferral.passages and deferral.partly:
                return deferral.valid_from
        return None


@dataclass(frozen=True)
class Document:
    """An official document and its editions, the oldest first."""

    key: str
    title: str
    kind: Kind
    publisher: str
    language: str
    page: str
    source_format: str
    editions: tuple[Edition, ...]


@dataclass(frozen=True)
class DatedPassage:
    """A passage and the days between which it applies: from ``valid_from`` up to, but not
    including, ``valid_to``, or for as long as the corpus knows when ``valid_to`` is None."""

    id: str
    document: str
    key: str
    label: str
    text: str
    heading: str | None
    part: str | None
    amended_by: tuple[str, ...]
    valid_from: date
    valid_to: date | None
    #: The day all of the passage applies, when some of its provisions apply later than the rest.
    fully_from: date | None
    version: str
    source_url: str

    @property
    def search_text(self) -> str:
        """What a keyword search compares: the label, the heading and the text, folded."""
        return fold(" ".join(filter(None, (self.label, self.heading, self.text))))

    @property
    def text_sha256(self) -> str:
        """A digest of what the passage says, so that a passage whose words change is embedded
        again and one whose words stay is not."""
        said = "\n".join((self.label, self.heading or "", self.part or "", self.text))
        return hashlib.sha256(said.encode()).hexdigest()

    def applies_on(self, day: date) -> bool:
        return self.valid_from <= day and (self.valid_to is None or day < self.valid_to)


@dataclass(frozen=True)
class Corpus:
    """Every document, and every passage with its days."""

    documents: tuple[Document, ...]
    passages: tuple[DatedPassage, ...] = field(init=False)

    def __post_init__(self) -> None:
        dated = tuple(passage for document in self.documents for passage in _dated(document))
        object.__setattr__(self, "passages", dated)

    def document(self, key: str) -> Document:
        for document in self.documents:
            if document.key == key:
                return document
        raise KeyError(key)

    def on(self, day: date) -> tuple[DatedPassage, ...]:
        """The passages that apply on ``day``."""
        return tuple(passage for passage in self.passages if passage.applies_on(day))

    def passage(self, document: str, key: str, day: date) -> DatedPassage | None:
        """The passage ``key`` of ``document`` that applies on ``day``, if one does."""
        for passage in self.passages:
            if passage.document == document and passage.key == key and passage.applies_on(day):
                return passage
        return None


def passage_id(document: str, key: str, valid_from: date) -> str:
    """A passage's id: its document, its key and the day it began to apply, readable and
    stable (``e-invoicing-law/article-4b/2027-07-01``)."""
    slug = re.sub(r"[^0-9a-z]+", "-", fold(key)).strip("-")
    return f"{document}/{slug}/{valid_from.isoformat()}"


# --- over time ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Open:
    passage: Passage
    edition: Edition
    start: date


def _dated(document: Document) -> Iterator[DatedPassage]:
    """The document's passages over time, each from the edition that gave it its wording."""
    current: dict[str, _Open] = {}
    for edition in document.editions:
        present = {passage.key: passage for passage in edition.passages}
        for key, earlier in list(current.items()):
            successor = present.get(key)
            if key in edition.renumbered or successor is None:
                end = edition.valid_from
            elif _same(earlier.passage, successor):
                continue
            else:
                end = edition.starts(key)
            del current[key]
            yield _dating(document, earlier, end)
        for key, passage in present.items():
            if key not in current:
                current[key] = _Open(passage, edition, edition.starts(key))
    for earlier in current.values():
        yield _dating(document, earlier, None)


def _same(earlier: Passage, later: Passage) -> bool:
    shown = ("label", "heading", "part", "text")
    return all(getattr(earlier, name) == getattr(later, name) for name in shown)


def _dating(document: Document, current: _Open, end: date | None) -> DatedPassage:
    passage, edition = current.passage, current.edition
    return DatedPassage(
        id=passage_id(document.key, passage.key, current.start),
        document=document.key,
        key=passage.key,
        label=passage.label,
        text=passage.text,
        heading=passage.heading,
        part=passage.part,
        amended_by=passage.amended_by,
        valid_from=current.start,
        valid_to=end,
        fully_from=edition.fully(passage.key),
        version=edition.version,
        source_url=edition.source_url,
    )


# --- the edition files --------------------------------------------------------------------------


def render_edition(title: str, passages: Iterable[Passage]) -> str:
    """The Markdown of an edition with ``passages``, as :func:`parse_edition` reads it."""
    lines = [f"# {_line(title, 'the title')}", ""]
    for passage in passages:
        values = {
            "label": passage.label,
            "heading": passage.heading,
            "part": passage.part,
            "amended-by": ", ".join(passage.amended_by) or None,
        }
        lines += [f"## {_line(passage.key, 'a key')}", ""]
        lines += [f"- {name}: {_line(value, name)}" for name, value in values.items() if value]
        lines += ["", *_text(passage), ""]
    return "\n".join(lines)


def _line(value: str, what: str) -> str:
    if not _LINE.match(value):
        raise CorpusError(f"{what} must be one line without spaces at its ends: {value!r}")
    return value


def _text(passage: Passage) -> list[str]:
    paragraphs = passage.text.split("\n\n")
    lines = [line for paragraph in paragraphs for line in paragraph.split("\n")]
    if (
        not passage.text
        or any(not _LINE.match(line) for line in lines)
        or any(line.startswith("#") for line in lines)
    ):
        raise CorpusError(
            f"passage '{passage.key}': its text must be paragraphs of lines without spaces at "
            "their ends, none of them starting with '#'"
        )
    out: list[str] = []
    for paragraph in paragraphs:
        out += [paragraph, ""]
    return out[:-1]


def parse_edition(markdown: str, *, where: str = "edition") -> tuple[str, tuple[Passage, ...]]:
    """The title and the passages of an edition's Markdown.

    Raises :class:`CorpusError` for anything that is not exactly what :func:`render_edition`
    writes, so that an edited file is noticed when the corpus is loaded.
    """
    lines = markdown.split("\n")
    if not lines[0].startswith("# ") or lines[1:2] != [""]:
        raise CorpusError(f"{where}:1: the file must start with '# <title>' and an empty line")
    title = lines[0][2:]
    blocks: list[tuple[int, list[str]]] = []
    for number, line in enumerate(lines[2:], start=3):
        if line.startswith("## "):
            blocks.append((number, [line]))
        elif blocks:
            blocks[-1][1].append(line)
        elif line:
            raise CorpusError(f"{where}:{number}: text before the first passage")
    passages = tuple(_passage(block, f"{where}:{number}") for number, block in blocks)
    if not passages:
        raise CorpusError(f"{where}: an edition without passages")
    keys = [passage.key for passage in passages]
    if repeated := sorted({key for key in keys if keys.count(key) > 1}):
        raise CorpusError(f"{where}: passages repeat the keys {', '.join(repeated)}")
    try:
        written = render_edition(title, passages)
    except CorpusError as error:
        raise CorpusError(f"{where}: {error}") from None
    if written != markdown:
        raise CorpusError(f"{where}: not as scripts/build_corpus.py writes it; rebuild the file")
    return title, passages


def _passage(block: list[str], where: str) -> Passage:
    key = block[0][3:]
    rest = block[1:]
    if rest[:1] != [""]:
        raise CorpusError(f"{where}: an empty line must follow '## {key}'")
    rest = rest[1:]
    values: dict[str, str] = {}
    while rest and rest[0].startswith("- "):
        name, colon, value = rest.pop(0)[2:].partition(": ")
        if not colon or name not in METADATA or name in values:
            raise CorpusError(f"{where}: '{name}' is not one of {', '.join(METADATA)}, once each")
        values[name] = value
    if "label" not in values or rest[:1] != [""]:
        raise CorpusError(f"{where}: passage '{key}' needs a label, then an empty line")
    text = "\n".join(rest[1:]).strip("\n")
    return Passage(
        key=key,
        label=values["label"],
        text=text,
        heading=values.get("heading"),
        part=values.get("part"),
        amended_by=tuple(values["amended-by"].split(", ")) if "amended-by" in values else (),
    )


# --- the manifest -------------------------------------------------------------------------------


def load_manifest(directory: Path) -> tuple[Document, ...]:
    """The documents and editions ``directory``'s manifest lists, without their passages."""
    manifest = directory / MANIFEST
    try:
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise CorpusError(f"{manifest}: {error}") from None
    documents = tuple(_document(entry) for entry in _list(data, "documents", "the manifest"))
    keys = [document.key for document in documents]
    if not documents or len(set(keys)) != len(keys):
        raise CorpusError(f"{manifest}: it must list documents, each key once")
    return documents


def load_corpus(directory: Path) -> Corpus:
    """The corpus in ``directory``: its manifest and every edition's file, checked."""
    documents: list[Document] = []
    for document in load_manifest(directory):
        editions: list[Edition] = []
        for edition in document.editions:
            try:
                markdown = (directory / edition.file).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as error:
                raise CorpusError(f"{edition.file}: {error}") from None
            title, passages = parse_edition(markdown, where=edition.file)
            if title != document.title:
                raise CorpusError(f"{edition.file}: the title must be '{document.title}'")
            editions.append(_with_passages(edition, passages, editions[-1] if editions else None))
        documents.append(replace(document, editions=tuple(editions)))
    return Corpus(tuple(documents))


def _with_passages(
    edition: Edition, passages: tuple[Passage, ...], earlier: Edition | None
) -> Edition:
    keys = {passage.key for passage in passages}
    for deferral in edition.deferred:
        if not set(deferral.passages) <= keys:
            unknown = ", ".join(sorted(set(deferral.passages) - keys))
            raise CorpusError(f"{edition.file}: deferred passages it does not have: {unknown}")
    if edition.renumbered:
        before = set() if earlier is None else {passage.key for passage in earlier.passages}
        if not set(edition.renumbered) <= before or not set(edition.renumbered.values()) <= keys:
            raise CorpusError(
                f"{edition.file}: 'renumbered' must map keys of the edition before it to keys "
                "of this one"
            )
    return replace(edition, passages=passages)


def _list(entry: dict[str, Any], name: str, where: str) -> list[dict[str, Any]]:
    value = entry.get(name, [])
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise CorpusError(f"{where}: '{name}' must be a list of tables")
    return value


def _required[T](entry: dict[str, Any], name: str, kind: type[T], where: str) -> T:
    value = entry.get(name)
    wrong = (
        not isinstance(value, kind)
        or (isinstance(value, str) and not _LINE.match(value))
        or (kind is date and isinstance(value, datetime))
    )
    if wrong:
        raise CorpusError(f"{where}: '{name}' must be a {kind.__name__}")
    return value  # type: ignore[return-value]  # an instance of kind, checked above


def _document(entry: dict[str, Any]) -> Document:
    key = _required(entry, "key", str, "the manifest")
    where = f"the manifest, document '{key}'"
    named = _required(entry, "kind", str, where)
    kind = next((kind for kind in _KINDS if kind == named), None)
    if kind is None:
        raise CorpusError(f"{where}: 'kind' must be one of {', '.join(_KINDS)}")
    editions = tuple(_edition(item, where) for item in _list(entry, "editions", where))
    days = [edition.valid_from for edition in editions]
    if not editions or days != sorted(set(days)) or editions[0].renumbered:
        raise CorpusError(
            f"{where}: its editions must be listed oldest first, one a day, and the first "
            "cannot renumber anything"
        )
    return Document(
        key=key,
        title=_required(entry, "title", str, where),
        kind=kind,
        publisher=_required(entry, "publisher", str, where),
        language=_required(entry, "language", str, where),
        page=_required(entry, "page", str, where),
        source_format=_required(entry, "source_format", str, where),
        editions=editions,
    )


def _edition(entry: dict[str, Any], document: str) -> Edition:
    file = _required(entry, "file", str, document)
    where = f"{document}, edition {file}"
    valid_from = _required(entry, "valid_from", date, where)
    sha256 = _required(entry, "sha256", str, where)
    if not _SHA256.match(sha256):
        raise CorpusError(f"{where}: 'sha256' must be 64 lowercase hexadecimal digits")
    deferred = []
    for item in _list(entry, "deferred", where):
        later = _required(item, "valid_from", date, where)
        keys = _required(item, "passages", list, where)
        partly = item.get("partly", False)
        if later <= valid_from or not keys or not all(isinstance(key, str) for key in keys):
            raise CorpusError(f"{where}: a deferral names passages and a later day")
        if not isinstance(partly, bool):
            raise CorpusError(f"{where}: 'partly' must be true or false")
        deferred.append(Deferral(tuple(keys), later, partly))
    named = [key for deferral in deferred for key in deferral.passages]
    if len(set(named)) != len(named):
        raise CorpusError(f"{where}: a passage is deferred once at most")
    renumbered = entry.get("renumbered", {})
    if not isinstance(renumbered, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in renumbered.items()
    ):
        raise CorpusError(f"{where}: 'renumbered' must map keys to keys")
    return Edition(
        file=file,
        valid_from=valid_from,
        version=_required(entry, "version", str, where),
        source_url=_required(entry, "source_url", str, where),
        source_file=_required(entry, "source_file", str, where),
        sha256=sha256,
        fetched_at=_required(entry, "fetched_at", date, where),
        deferred=tuple(deferred),
        renumbered=dict(renumbered),
    )
