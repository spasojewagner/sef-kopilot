"""The reading's evaluations: the golden invoices and their documents, how fields read are
compared with them, and the measures."""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from einvoice_core.pipeline import validate
from sef_api.extraction.documents import LONGEST_SIDE, open_document
from sef_api.extraction.draft import draft
from sef_api.extraction.fields import InvoiceFields, Line, Totals
from sef_api.llm import LLMError, Message
from sef_evals.cassettes import picture_digest
from sef_evals.extraction import (
    DOCUMENTS,
    FORMS,
    ExtractionGolden,
    Read,
    differences,
    load_golden,
    measure,
    read,
)
from sef_evals.golden import GoldenError

from .conftest import REPOSITORY_ROOT, needs_rulesets

GOLDEN = load_golden(REPOSITORY_ROOT / "evals" / "golden" / "extraction.yaml")
CASE = next(case for case in GOLDEN.cases if case.name == "consulting-hours")


class Reading:
    """A stand-in for the reading model: it reads every document as ``fields``, or answers it
    as written, or fails as ``failures`` say, in turn."""

    model = "test/reading"

    def __init__(self, fields: InvoiceFields | str, *failures: str) -> None:
        self.fields = fields
        self.failures = list(failures)
        self.shown: list[int] = []

    async def answer(
        self,
        messages: Sequence[Message],
        *,
        name: str,  # noqa: ARG002
        schema: Mapping[str, Any],  # noqa: ARG002
        max_tokens: int | None = None,  # noqa: ARG002
    ) -> str:
        self.shown.append(len(messages[-1].pictures))
        if self.failures:
            raise LLMError(self.failures.pop(0))
        if isinstance(self.fields, str):
            return self.fields
        return self.fields.model_dump_json()

    async def aclose(self) -> None:
        pass


@pytest.fixture
def one_case(tmp_path: Path) -> ExtractionGolden:
    """A repository with one golden invoice printed three ways."""
    (tmp_path / DOCUMENTS).mkdir(parents=True)
    for form in FORMS:
        shutil.copy(REPOSITORY_ROOT / CASE.document(form), tmp_path / DOCUMENTS)
    return ExtractionGolden(cases=(CASE,))


# --- the golden set -------------------------------------------------------------------------


@needs_rulesets
@pytest.mark.parametrize("case", GOLDEN.cases, ids=lambda case: case.name)
def test_every_golden_invoice_makes_an_invoice_the_validator_accepts(case: Any) -> None:
    report = validate(draft(case.fields), profile="srb")
    assert report.valid, [violation.rule_id for violation in report.violations]


@pytest.mark.parametrize("case", GOLDEN.cases, ids=lambda case: case.name)
async def test_every_golden_invoice_is_printed_three_ways_the_api_reads(case: Any) -> None:
    pdf, scan, photo = [
        await open_document((REPOSITORY_ROOT / case.document(form)).read_bytes(), media_type)
        for form, (_, media_type) in FORMS.items()
    ]
    assert (len(pdf.pages), len(scan.pages), len(photo.pages)) == (1, 1, 1)
    # The PDF as a business program prints it, its text given; a scan and a photograph without.
    text = pdf.pages[0].text
    assert text is not None
    assert case.fields.number in text
    assert not scan.has_text
    assert photo.kind == "picture"


def test_the_golden_invoices_are_varied() -> None:
    fields = [case.fields for case in GOLDEN.cases]
    assert len(GOLDEN.cases) >= 10
    assert {case.layout for case in GOLDEN.cases} == {"classic", "modern"}
    assert {f.type_code for f in fields} == {"380", "383", "386"}
    assert {line.vat_rate for f in fields for line in f.lines} == {"10", "20"}
    assert max(len(f.lines) for f in fields) >= 10
    assert any(not (f.seller.name or "").isascii() for f in fields)  # Cyrillic
    assert any(f.delivery_date is None for f in fields)
    assert any(f.payment.model is None for f in fields)


def test_names_every_document_it_has(tmp_path: Path) -> None:
    on_disk = {path.name for path in (REPOSITORY_ROOT / DOCUMENTS).iterdir()}
    named = {case.document(form).name for case in GOLDEN.cases for form in FORMS}
    assert on_disk == named


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("cases: []\n", "extraction.yaml: "),
        ("cases: [{name: a, layout: plain, fields: {}}]\n", "extraction.yaml: "),
        (
            "cases: [{name: a, layout: classic, fields: {}}, {name: a, layout: modern, "
            "fields: {}}]\n",
            "cases named more than once: a",
        ),
    ],
)
def test_refuses_a_golden_set_it_cannot_read(tmp_path: Path, text: str, problem: str) -> None:
    path = tmp_path / "extraction.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(GoldenError, match=problem):
        load_golden(path)


# --- comparing fields read with the invoice's ------------------------------------------------


def test_fields_read_as_the_invoice_has_them_differ_in_nothing() -> None:
    found = differences(CASE.fields, CASE.fields)
    assert (found.misread, found.invented) == ((), ())
    # Its fields, one line and one row of the recapitulation among them; and those it leaves
    # empty: the buyer's email and what was paid in advance.
    assert (found.has, found.leaves) == (42, 2)


def test_amounts_are_compared_as_numbers_and_text_without_its_spaces() -> None:
    line = CASE.fields.lines[0].model_copy(
        update={"quantity": "8.000", "name": "  Konsultantski   sat "}
    )
    read_ = CASE.fields.model_copy(update={"lines": [line]})
    assert differences(read_, CASE.fields).misread == ()


def test_a_value_read_otherwise_or_not_at_all_is_misread() -> None:
    read_ = CASE.fields.model_copy(
        update={
            "number": "RF-2026-000128",
            "totals": CASE.fields.totals.model_copy(update={"payable": None}),
        }
    )
    assert differences(read_, CASE.fields).misread == (
        "number read as 'RF-2026-000128', the invoice has 'RF-2026-000123'",
        "totals.payable not read, the invoice has '14400.00'",
    )


def test_a_line_missed_counts_every_field_and_a_line_made_up_is_invented() -> None:
    missed = differences(CASE.fields.model_copy(update={"lines": []}), CASE.fields)
    assert len(missed.misread) == len(Line.model_fields)
    extra = Line(name="Putni troškovi", quantity="1", net_amount="2000.00")
    added = differences(
        CASE.fields.model_copy(update={"lines": [*CASE.fields.lines, extra]}), CASE.fields
    )
    assert added.misread == ()
    assert added.invented == (
        "lines[2].name filled in as 'Putni troškovi'",
        "lines[2].quantity filled in as '1'",
        "lines[2].net_amount filled in as '2000.00'",
    )
    assert added.leaves == 2 + len(Line.model_fields)


def test_a_field_the_invoice_leaves_empty_and_the_reading_fills_in_is_invented() -> None:
    read_ = CASE.fields.model_copy(
        update={"buyer": CASE.fields.buyer.model_copy(update={"email": "kupac@ogled.example"})}
    )
    found = differences(read_, CASE.fields)
    assert found.invented == ("buyer.email filled in as 'kupac@ogled.example'",)


# --- reading, and the measures --------------------------------------------------------------


async def test_reads_each_document_as_the_api_does(
    tmp_path: Path, one_case: ExtractionGolden
) -> None:
    model = Reading(CASE.fields)
    names: dict[str, str] = {}
    told: list[str] = []

    done = await read(tmp_path, one_case, model, names=names, progress=told.append)

    assert [(each.id, each.problem) for each in done] == [
        ("consulting-hours.pdf", None),
        ("consulting-hours.scan.pdf", None),
        ("consulting-hours.jpg", None),
    ]
    assert told == [f"the reading of {each.id}" for each in done]
    assert model.shown == [1, 1, 1]
    # Each page shown is named by the document it was drawn from, as a cassette's key names it.
    assert len(names) == 3
    assert all(
        name.startswith("consulting-hours.") and " page 1 " in name and name.endswith(" q85")
        for name in names.values()
    )
    pdf = names[
        picture_digest(
            (await open_document((tmp_path / CASE.document("pdf")).read_bytes(), "application/pdf"))
            .pages[0]
            .picture
        )
    ]
    assert f"x{LONGEST_SIDE} " in pdf


async def test_a_document_read_whole_meets_every_measure(
    tmp_path: Path, one_case: ExtractionGolden
) -> None:
    done = await read(tmp_path, one_case, Reading(CASE.fields))

    measures = {m.name: m for m in measure(done)}

    assert list(measures) == [
        "extraction_pdf",
        "extraction_scan",
        "extraction_photo",
        "extraction_invented",
        "extraction_valid",
    ]
    assert [(m.value, m.total) for m in measures.values()] == [
        (1.0, 42),
        (1.0, 42),
        (1.0, 42),
        (0.0, 6),
        (1.0, 3),
    ]
    assert measures["extraction_photo"].title == (
        "Fields read as the invoice has them, from a photograph"
    )


async def test_a_reading_that_misreads_a_total_makes_an_invoice_the_validator_refuses(
    tmp_path: Path, one_case: ExtractionGolden
) -> None:
    misread = CASE.fields.model_copy(
        update={"totals": Totals(**{**CASE.fields.totals.model_dump(), "payable": "14000.00"})}
    )
    done = await read(tmp_path, one_case, Reading(misread))

    measures = {m.name: m for m in measure(done)}

    assert measures["extraction_photo"].failures == (
        "consulting-hours.jpg: totals.payable read as '14000.00', the invoice has '14400.00'",
    )
    assert measures["extraction_valid"].value == 0.0
    assert all(
        failure.endswith("the validator reports BR-CO-16")
        for failure in measures["extraction_valid"].failures
    ), measures["extraction_valid"].failures


async def test_a_document_not_read_counts_every_field_against_it(
    tmp_path: Path, one_case: ExtractionGolden
) -> None:
    model = Reading(CASE.fields, "no answer is recorded for this request")

    done = await read(tmp_path, one_case, model)

    assert done[0] == Read(CASE, "pdf", None, "no answer is recorded for this request")
    measures = {m.name: m for m in measure(done)}
    assert (measures["extraction_pdf"].value, measures["extraction_scan"].value) == (0.0, 1.0)
    assert measures["extraction_pdf"].failures[0] == (
        "consulting-hours.pdf: type_code not read, the invoice has '380'"
    )
    assert measures["extraction_valid"].failures == (
        "consulting-hours.pdf: not read: no answer is recorded for this request",
    )


async def test_a_reading_answered_in_no_form_of_fields_is_not_read(
    tmp_path: Path, one_case: ExtractionGolden
) -> None:
    done = await read(tmp_path, one_case, Reading(json.dumps({"number": 7})))

    assert all(each.fields is None for each in done)
    assert all("did not have the form of an invoice's fields" in str(each.problem) for each in done)


async def test_a_document_missing_from_the_golden_set_is_said(tmp_path: Path) -> None:
    with pytest.raises(GoldenError, match=r"consulting-hours: .*\(run scripts/render_documents"):
        await read(tmp_path, ExtractionGolden(cases=(CASE,)), Reading(CASE.fields))


async def test_a_document_that_is_not_one_is_said(
    tmp_path: Path, one_case: ExtractionGolden
) -> None:
    (tmp_path / CASE.document("pdf")).write_bytes(b"not a PDF")
    with pytest.raises(GoldenError, match=r"consulting-hours.pdf: the document is not a PDF"):
        await read(tmp_path, one_case, Reading(CASE.fields))
