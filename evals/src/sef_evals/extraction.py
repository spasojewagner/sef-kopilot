"""The reading's evaluations: synthetic invoices printed as PDFs, scans and photographs, read
back into their fields (ADR-0063).

``evals/golden/extraction.yaml`` names invoices by the fields they print and the layout they are
printed in; ``scripts/render_documents.py`` prints each in ``evals/golden/documents/`` three
ways: ``<name>.pdf``, a PDF with its text layer, as a business program prints one;
``<name>.scan.pdf``, the page scanned, a grey picture in a PDF without text; and ``<name>.jpg``,
the paper photographed on a desk. Each document is opened as the API opens one, and read by the
reading model as the API reads it (:class:`sef_api.extraction.reader.Reader`), from a cassette
(:mod:`sef_evals.cassettes`).

- ``extraction_pdf``, ``extraction_scan``, ``extraction_photo``: of the fields a document's
  invoice has, the share read as it has them, one measure for each way it is printed; amounts
  are compared as numbers, text with its spaces collapsed, and a line the model missed counts
  every one of its fields;
- ``extraction_invented``: of the fields the invoice leaves empty, the share the model filled
  in all the same, an invented line's fields among them (the reading must not guess);
- ``extraction_valid``: of the documents, the share whose fields, as read, make an invoice the
  validator accepts without a correction.

The golden fields are the reference: every case's fields make an invoice the validator accepts,
which the tests check, so a reading that does not is the reading's fault.
"""

from __future__ import annotations

import hashlib
import io
import unicodedata
from collections.abc import Callable, MutableMapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Final, Literal

import yaml
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from einvoice_core.pipeline import validate
from einvoice_core.violations import Severity
from sef_api.extraction.documents import QUALITY, UnreadableDocumentError, open_document
from sef_api.extraction.draft import draft
from sef_api.extraction.fields import InvoiceFields, Line, VatSubtotal
from sef_api.extraction.reader import Reader, ReadingError
from sef_api.llm import LLMClient, LLMError
from sef_evals.cassettes import picture_digest
from sef_evals.golden import GoldenError
from sef_evals.measures import Measure

__all__ = [
    "DOCUMENTS",
    "FORMS",
    "Differences",
    "ExtractionCase",
    "ExtractionGolden",
    "Form",
    "Read",
    "differences",
    "load_golden",
    "measure",
    "read",
]

#: How an invoice is printed: a PDF with text, a scan, a photograph.
Form = Literal["pdf", "scan", "photo"]
#: Each form's file, after the case's name, and its media type.
FORMS: Final[dict[Form, tuple[str, str]]] = {
    "pdf": (".pdf", "application/pdf"),
    "scan": (".scan.pdf", "application/pdf"),
    "photo": (".jpg", "image/jpeg"),
}
#: Where the documents are, from the repository's root.
DOCUMENTS: Final = Path("evals/golden/documents")
#: Seconds one reading may take: the real model is slow, and waits for its limits.
_SECONDS: Final = 1200.0
#: The fields compared as numbers: 8 and 8.00 are the same quantity.
_NUMBERS: Final = frozenset(
    {
        "quantity",
        "unit_price",
        "net_amount",
        "vat_rate",
        "taxable_amount",
        "tax_amount",
        "line_total",
        "tax_exclusive",
        "tax",
        "tax_inclusive",
        "prepaid",
        "payable",
    }
)

Value = str | bool | None


class ExtractionCase(BaseModel):
    """An invoice, by the fields it prints, and the layout it is printed in."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    layout: Literal["classic", "modern"]
    fields: InvoiceFields

    def document(self, form: Form) -> Path:
        """The case's document printed as ``form``, from the repository's root."""
        return DOCUMENTS / f"{self.name}{FORMS[form][0]}"


class ExtractionGolden(BaseModel):
    """The golden set of the reading."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cases: tuple[ExtractionCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _named_once(self) -> ExtractionGolden:
        names = [case.name for case in self.cases]
        if twice := sorted({name for name in names if names.count(name) > 1}):
            raise ValueError(f"cases named more than once: {', '.join(twice)}")
        return self


def load_golden(path: Path) -> ExtractionGolden:
    try:
        return ExtractionGolden.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (yaml.YAMLError, ValidationError) as error:
        raise GoldenError(f"{path.name}: {error}") from None


@dataclass(frozen=True)
class Read:
    """A case's document printed as ``form``, and the fields read from it, or why none were."""

    case: ExtractionCase
    form: Form
    fields: InvoiceFields | None
    problem: str | None

    @property
    def id(self) -> str:
        """The document, as a report names it."""
        return self.case.document(self.form).name


def _flat(fields: InvoiceFields, lines: int, rows: int) -> dict[str, Value]:
    """Every field of ``fields`` by its path, ``lines`` lines and ``rows`` rows of the VAT
    recapitulation of them, a line or a row it does not have as empty fields."""
    flat: dict[str, Value] = {}
    data = fields.model_dump(mode="json")
    for key, value in data.items():
        if key in ("lines", "vat_breakdown"):
            continue
        if isinstance(value, dict):
            flat.update({f"{key}.{inner}": each for inner, each in value.items()})
        else:
            flat[key] = value
    for key, count, model in (
        ("lines", lines, data["lines"]),
        ("vat_breakdown", rows, data["vat_breakdown"]),
    ):
        names = (Line if key == "lines" else VatSubtotal).model_fields
        for number in range(1, count + 1):
            item = model[number - 1] if number <= len(model) else {}
            flat.update({f"{key}[{number}].{name}": item.get(name) for name in names})
    return flat


def _same(path: str, read: Value, printed: Value) -> bool:
    """Whether ``read`` is what the invoice has, ``printed``."""
    if isinstance(read, str) and isinstance(printed, str):
        if path.rsplit(".", 1)[-1] in _NUMBERS:
            # The fields' forms have already held the reading to numbers.
            return Decimal(read) == Decimal(printed)
        return _text(read) == _text(printed)
    return read == printed


def _text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split())


@dataclass(frozen=True)
class Differences:
    """How fields read differ from the invoice's: the fields it has that were read otherwise or
    not at all, of how many it has; and the fields it leaves empty that were filled in, of how
    many it leaves empty."""

    misread: tuple[str, ...]
    has: int
    invented: tuple[str, ...]
    leaves: int


def differences(read: InvoiceFields, invoice: InvoiceFields) -> Differences:
    """How ``read`` differs from the fields of ``invoice``."""
    lines = max(len(read.lines), len(invoice.lines))
    rows = max(len(read.vat_breakdown), len(invoice.vat_breakdown))
    got, want = _flat(read, lines, rows), _flat(invoice, lines, rows)
    misread: list[str] = []
    invented: list[str] = []
    for path, value in want.items():
        if value is None:
            if got[path] is not None:
                invented.append(f"{path} filled in as {got[path]!r}")
        elif got[path] is None:
            misread.append(f"{path} not read, the invoice has {value!r}")
        elif not _same(path, got[path], value):
            misread.append(f"{path} read as {got[path]!r}, the invoice has {value!r}")
    leaves = sum(1 for value in want.values() if value is None)
    return Differences(tuple(misread), len(want) - leaves, tuple(invented), leaves)


def _name_pages(
    names: MutableMapping[str, str], data: bytes, path: Path, pictures: Sequence[bytes]
) -> None:
    """Name each page's picture by the document it was drawn from, so that a cassette recorded
    on one machine answers the same document on another, where drawing it may differ in its
    last bits: the document's digest, the page, its size and the quality it was encoded at."""
    digest = hashlib.sha256(data).hexdigest()
    for number, picture in enumerate(pictures, start=1):
        width, height = Image.open(io.BytesIO(picture)).size
        names[picture_digest(picture)] = (
            f"{path.name} {digest} page {number} {width}x{height} q{QUALITY}"
        )


async def read(
    root: Path,
    golden: ExtractionGolden,
    llm: LLMClient,
    *,
    names: MutableMapping[str, str] | None = None,
    progress: Callable[[str], None] | None = None,
) -> list[Read]:
    """Each case's documents read by ``llm`` as the API reads an upload. ``names`` is given
    the name of each picture shown, for the cassette's keys; ``progress`` is told each document
    in turn."""
    reader = Reader(llm)
    done: list[Read] = []
    for case in golden.cases:
        for form, (_, media_type) in FORMS.items():
            path = case.document(form)
            if progress is not None:
                progress(f"the reading of {path.name}")
            try:
                data = (root / path).read_bytes()
            except OSError as error:
                raise GoldenError(
                    f"extraction: {case.name}: {error} (run scripts/render_documents.py)"
                ) from None
            try:
                document = await open_document(data, media_type)
            except UnreadableDocumentError as error:
                raise GoldenError(f"extraction: {path.name}: {error}") from None
            if names is not None:
                _name_pages(names, data, path, [page.picture.data for page in document.pages])
            try:
                reading = await reader.read(document, seconds=_SECONDS)
            except (ReadingError, LLMError) as error:
                done.append(Read(case, form, None, str(error)))
            else:
                done.append(Read(case, form, reading.fields, None))
    return done


def measure(done: Sequence[Read]) -> list[Measure]:
    """The reading's measures on what was ``done``."""
    measures: list[Measure] = []
    invented: list[str] = []
    empty = 0
    for form, title in _FORM_TITLES.items():
        failures: list[str] = []
        total = 0
        for each in (each for each in done if each.form == form):
            found = differences(each.fields or InvoiceFields(), each.case.fields)
            failures += [f"{each.id}: {line}" for line in found.misread]
            invented += [f"{each.id}: {line}" for line in found.invented]
            total += found.has
            empty += found.leaves
        measures.append(
            Measure(
                name=f"extraction_{form}",
                title=f"Fields read as the invoice has them, from {title}",
                kind="share",
                total=total,
                failures=tuple(failures),
            )
        )
    measures += [
        Measure(
            name="extraction_invented",
            title="Fields the invoice leaves empty that the reading filled in",
            kind="rate",
            total=empty,
            failures=tuple(invented),
        ),
        Measure(
            name="extraction_valid",
            title="Documents read into an invoice the validator accepts as it was read",
            kind="share",
            total=len(done),
            failures=tuple(
                f"{each.id}: {problem}" for each in done if (problem := _invalid(each)) is not None
            ),
        ),
    ]
    return measures


_FORM_TITLES: Final[dict[Form, str]] = {
    "pdf": "a PDF with its text",
    "scan": "a scan",
    "photo": "a photograph",
}


def _invalid(each: Read) -> str | None:
    """Why the invoice read from a document is not accepted as it was read; None when it is."""
    if each.fields is None:
        return f"not read: {each.problem}"
    report = validate(draft(each.fields), profile="srb")
    fatal = sorted({v.rule_id for v in report.violations if v.severity is Severity.FATAL})
    return f"the validator reports {', '.join(fatal)}" if fatal else None
