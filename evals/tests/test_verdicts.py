"""The validator's measures: beside the reference, and against the golden labels."""

from __future__ import annotations

import shutil
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from einvoice_core.pipeline import ValidationReport, validate
from sef_evals.golden import Case, Expect
from sef_evals.measures import Measure
from sef_evals.verdicts import Reference, measure, reference

from .conftest import MUTATIONS_DIR, REPOSITORY_ROOT, SYNTHETIC_DIR, needs_rulesets

pytestmark = needs_rulesets

MINIMAL = "fixtures/invoices/synthetic/srb-minimal-invoice.xml"
FINAL = "fixtures/invoices/synthetic/srb-final-invoice.xml"
PIB = "fixtures/invoices/synthetic/mutations/srb-009-pib-check-digit.xml"
AMPERSAND = "fixtures/invoices/synthetic/mutations/xml-unescaped-ampersand.xml"
DATE = "fixtures/invoices/synthetic/mutations/xsd-date-format.xml"


def case(document: str, expect: Expect, *reports: str, profile: str = "srb") -> Case:
    return Case(document, "test", profile, expect, Counter(reports))


def by_name(measures: list[Measure]) -> dict[str, Measure]:
    return {m.name: m for m in measures}


def test_the_reference_applies_the_published_artefacts_as_published() -> None:
    assert reference(SYNTHETIC_DIR / "srb-minimal-invoice.xml", "en16931") == Reference(
        valid=True, fatal=Counter()
    )
    # Unread, refused by the schema, or by EN 16931's rules, whatever SRB-CIUS says.
    assert reference(REPOSITORY_ROOT / AMPERSAND, "en16931") == Reference(
        valid=False, fatal=Counter({"XML": 1})
    )
    assert reference(REPOSITORY_ROOT / DATE, "en16931") == Reference(
        valid=False, fatal=Counter({"XSD": 1})
    )
    seller = reference(MUTATIONS_DIR / "br-06-seller-name.xml", "en16931")
    assert not seller.valid
    assert seller.fatal["BR-06"] == 1


def test_the_reference_reports_nothing_counted_inside_the_extension() -> None:
    """CEN's stylesheet judges the Serbian extension's copies of the totals; what it reports
    there is not compared (ADR-0007), though it still decides the verdict."""
    judged = reference(REPOSITORY_ROOT / FINAL, "en16931")
    assert not judged.valid
    assert "BR-CO-10" not in judged.fatal
    assert "BR-CO-13" not in judged.fatal


def test_measures_the_golden_cases() -> None:
    measured = by_name(
        measure(
            REPOSITORY_ROOT,
            [
                case(MINIMAL, "accept"),
                case(MINIMAL, "accept", profile="en16931"),
                case(FINAL, "accept"),
                case(PIB, "reject", "SRB-009", "SRB-009"),
                case(AMPERSAND, "reject", "XML"),
            ],
        )
    )
    assert list(measured) == [
        "agreement",
        "rule_agreement",
        "false_accept_rate",
        "false_reject_rate",
        "detection",
    ]
    # Four documents beside the reference: the minimal invoice once, under EN 16931.
    assert (measured["agreement"].total, measured["agreement"].failures) == (4, ())
    assert (measured["rule_agreement"].total, measured["rule_agreement"].failures) == (4, ())
    assert (measured["false_accept_rate"].total, measured["false_accept_rate"].value) == (2, 0)
    assert (measured["false_reject_rate"].total, measured["false_reject_rate"].value) == (3, 0)
    assert (measured["detection"].total, measured["detection"].value) == (2, 1)


def test_names_the_documents_that_fail_their_labels() -> None:
    measured = by_name(
        measure(
            REPOSITORY_ROOT,
            [
                case(MINIMAL, "reject", "BR-01"),
                case(PIB, "accept"),
                case(PIB, "reject", "SRB-009", "SRB-009", "SRB-009", profile="en16931"),
            ],
        )
    )
    assert measured["false_accept_rate"].failures == (
        f"{MINIMAL} [srb]: accepted",
        f"{PIB} [en16931]: accepted",
    )
    assert measured["false_reject_rate"].failures == (f"{PIB} [srb]: rejected for SRB-009 (2)",)
    assert measured["detection"].failures == (
        f"{MINIMAL} [srb]: BR-01 not reported",
        f"{PIB} [en16931]: SRB-009 (3) not reported",
    )
    assert measured["detection"].value == 0


def test_names_the_documents_on_which_it_differs_from_the_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A validator that accepted the mistaken PIB under EN 16931, or reported another rule,
    would differ from the reference; the measure says where."""

    def lenient(path: Path, profile: str, **options: Any) -> ValidationReport:
        report = validate(path, profile, **options)
        if path.name == "br-06-seller-name.xml":
            return report.model_copy(update={"valid": True})
        if path.name == "br-25-item-name.xml":
            renamed = [v.model_copy(update={"rule_id": "BR-99"}) for v in report.violations]
            return report.model_copy(update={"violations": tuple(renamed)})
        return report

    monkeypatch.setattr("sef_evals.verdicts.validate", lenient)
    seller = "fixtures/invoices/synthetic/mutations/br-06-seller-name.xml"
    item = "fixtures/invoices/synthetic/mutations/br-25-item-name.xml"
    measured = by_name(
        measure(
            REPOSITORY_ROOT, [case(seller, "reject"), case(item, "reject"), case(PIB, "reject")]
        )
    )
    assert measured["agreement"].failures == (
        f"{seller} [en16931]: the reference rejects it, the validator accepts it",
    )
    assert measured["rule_agreement"].failures == (
        f"{item} [en16931]: the validator reports BR-99 more, BR-25 fewer than the reference",
    )
    assert measured["agreement"].total == 3


def test_a_case_needs_no_copy_of_its_document(tmp_path: Path) -> None:
    """The documents are read where the root says, so a measure of a moved repository holds."""
    (tmp_path / "docs").mkdir()
    shutil.copy(REPOSITORY_ROOT / PIB, tmp_path / "docs" / "pib.xml")
    (detection,) = [
        m
        for m in measure(tmp_path, [case("docs/pib.xml", "reject", "SRB-009")])
        if m.name == "detection"
    ]
    assert detection.failures == ()
