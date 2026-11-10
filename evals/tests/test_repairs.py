"""The repairs' evaluations: the golden set, the invoices made from it, and what repairs leave."""

from __future__ import annotations

from pathlib import Path

import pytest

from einvoice_core.pipeline import validate
from sef_evals.golden import GoldenError
from sef_evals.repairs import RepairCase, RepairGolden, document_of, load_golden, measure, repair

from .conftest import REPOSITORY_ROOT, Explaining, needs_rulesets

MINIMAL = "fixtures/invoices/synthetic/srb-minimal-invoice.xml"
MUTATIONS = "fixtures/invoices/synthetic/mutations"
PROFORMA = (("<cbc:InvoiceTypeCode>380<", "<cbc:InvoiceTypeCode>325<"),)


def case(name: str, document: str, expect: str, *edits: tuple[str, str]) -> RepairCase:
    return RepairCase.model_validate(
        {"name": name, "document": document, "mistake": "m.", "edits": edits, "expect": expect}
    )


def golden(*cases: RepairCase) -> RepairGolden:
    return RepairGolden(language="sr", cases=cases)


@needs_rulesets
def test_every_case_of_the_repository_has_the_mistake_it_names() -> None:
    loaded = load_golden(REPOSITORY_ROOT / "evals" / "golden" / "repairs.yaml")
    assert loaded.language == "sr"
    kinds = [c.expect for c in loaded.cases]
    assert (kinds.count("repaired"), kinds.count("refused")) == (9, 11)
    for each in loaded.cases:
        report = validate(document_of(REPOSITORY_ROOT, each), "srb")
        assert not report.valid, each.name
    # The held-out invoices are made at run time, never copies of the fixtures.
    assert all(c.edits for c in loaded.cases if c.expect == "repaired")
    assert not any("/mutations/" in c.document for c in loaded.cases if c.expect == "repaired")


def test_makes_a_case_s_invoice_by_its_edits() -> None:
    made = document_of(REPOSITORY_ROOT, case("p", MINIMAL, "repaired", *PROFORMA)).decode()
    assert "<cbc:InvoiceTypeCode>325</cbc:InvoiceTypeCode>" in made
    assert "<cbc:InvoiceTypeCode>380<" not in made
    as_is = document_of(REPOSITORY_ROOT, case("p", MINIMAL, "refused"))
    assert as_is == (REPOSITORY_ROOT / MINIMAL).read_bytes()


@pytest.mark.parametrize(
    ("edits", "problem"),
    [
        ((("<cbc:InvoiceTypeCode>999<", "x"),), "occurs 0 times, not once"),
        ((("<cbc:IdentificationCode>RS<", "x"),), "occurs 2 times, not once"),
    ],
)
def test_an_edit_occurs_once(edits: tuple[tuple[str, str], ...], problem: str) -> None:
    with pytest.raises(GoldenError, match=f"repairs: p: .* {problem}"):
        document_of(REPOSITORY_ROOT, case("p", MINIMAL, "repaired", *edits))


def test_a_case_needs_its_document() -> None:
    with pytest.raises(GoldenError, match=r"repairs: p: .*nowhere\.xml"):
        document_of(REPOSITORY_ROOT, case("p", "nowhere.xml", "repaired"))


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        (
            "language: sr\ncases:\n"
            "  - {name: a, document: d.xml, mistake: m, expect: refused}\n"
            "  - {name: a, document: e.xml, mistake: m, expect: refused}\n",
            "cases named more than once: a",
        ),
        ("language: sr\ncases:\n  - {name: a, document: d, mistake: m, expect: fixed}\n", "expect"),
        ("language: sr\ncases:\n  - {name: A, document: d, mistake: m, expect: refused}\n", "name"),
        ("language: de\ncases:\n  - {name: a, document: d, mistake: m, expect: refused}\n", "lang"),
        ("language: sr\ncases: []\n", "cases"),
        ("language: [\n", "repairs.yaml"),
    ],
)
def test_refuses_a_golden_set_it_cannot_trust(tmp_path: Path, text: str, problem: str) -> None:
    path = tmp_path / "repairs.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(GoldenError, match=problem):
        load_golden(path)


@needs_rulesets
async def test_measures_what_the_repairs_leave() -> None:
    told: list[str] = []
    tried = await repair(
        REPOSITORY_ROOT,
        golden(
            case("proforma", MINIMAL, "repaired", *PROFORMA),
            case("pib", f"{MUTATIONS}/srb-009-pib-check-digit.xml", "refused"),
            case("status", f"{MUTATIONS}/srb-014-seller-vat-status-value.xml", "refused"),
            case("rate", f"{MUTATIONS}/srb-021-vat-rate.xml", "repaired"),
        ),
        Explaining(),
        progress=told.append,
    )
    assert told == [
        "the repair of proforma",
        "the repair of pib",
        "the repair of status",
        "the repair of rate",
    ]
    assert [t.accepted for t in tried] == [True, False, False, False]
    # A PIB the question does not hold is a value the model made up: its answer is refused,
    # and the stand-in, told so, proposes nothing.
    assert tried[1].outcome() == (
        "no repair: the language model proposes no patch for these violations: a person must"
    )
    # A patch in the tax scheme is for a person to decide, and the invoice is not accepted.
    assert tried[2].outcome() == "SRB-014 left, 1 patches for a person to decide"
    assert tried[3].outcome().startswith("no repair: ")
    success, overreach = measure(tried)
    assert (success.name, success.total, success.passed) == ("repair_success", 2, 1)
    assert success.failures == (f"rate: {tried[3].outcome()}",)
    assert (overreach.name, overreach.total, overreach.failures) == ("overreach_rate", 2, ())


@needs_rulesets
async def test_a_repair_that_makes_a_refused_invoice_pass_overreaches() -> None:
    tried = await repair(
        REPOSITORY_ROOT, golden(case("proforma", MINIMAL, "refused", *PROFORMA)), Explaining()
    )
    (_, overreach) = measure(tried)
    assert overreach.failures == ("proforma: the validator accepts the invoice the repair left",)
    assert overreach.value == 1


@needs_rulesets
async def test_a_case_whose_invoice_cannot_be_patched_is_a_golden_set_to_fix() -> None:
    unreadable = case("ampersand", f"{MUTATIONS}/xml-unescaped-ampersand.xml", "refused")
    with pytest.raises(GoldenError, match="repairs: ampersand: the invoice cannot be patched: "):
        await repair(REPOSITORY_ROOT, golden(unreadable), Explaining())
