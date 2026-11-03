"""Conformance of the Schematron layer with the official rule sets and their unit tests.

CEN/TC 434 publishes unit tests next to its rules, in the VEFA ``testSet`` format: small
documents, each annotated with the outcomes the publisher expects. Every expectation of every
published test is checked here:

* ``success`` - the rule is not reported;
* ``error`` - the rule is reported as fatal, exactly ``number`` times when that is given;
* ``warning`` - the rule is reported as a warning, exactly ``number`` times when given.

(A ``number`` on ``success`` counts evaluations that passed, which SVRL does not report.)

These tests apply the fetched third-party rule sets (``make rulesets``) and are marked
``conformance``; ``pytest -m "not conformance"`` leaves them out of a quick local run.
"""

from __future__ import annotations

import copy
import statistics
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pytest
from lxml import etree

from einvoice_core import schematron
from einvoice_core.rulesets import RulesetNotFoundError, ruleset_path
from einvoice_core.schematron import SchematronValidator
from einvoice_core.violations import Severity, Violation, is_valid
from einvoice_core.xml import load_document

from .conftest import SYNTHETIC_DIR, THIRD_PARTY


def _fetched(*packages: str) -> bool:
    try:
        for package in packages:
            ruleset_path(package)
    except RulesetNotFoundError:
        return False
    return True


pytestmark = [
    pytest.mark.conformance,
    pytest.mark.skipif(
        not _fetched("en16931"),
        reason="rule sets not fetched (run `make rulesets`)",
    ),
]

VEFA = "http://difi.no/xsd/vefa/validator/1.0"

CEN_UNIT_TESTS = sorted((THIRD_PARTY / "en16931" / "test").glob("*-unit-UBL/*.xml"))
CEN_EXAMPLES = sorted((THIRD_PARTY / "en16931" / "ubl" / "examples").glob("ubl-tc434-*.xml"))
SYNTHETIC_FIXTURES = sorted(SYNTHETIC_DIR.glob("*.xml"))

Outcome = Literal["success", "error", "warning"]
_OUTCOMES: dict[str, Outcome] = {"success": "success", "error": "error", "warning": "warning"}


@dataclass(frozen=True)
class Expectation:
    """One published expectation: what a rule must report for a test document."""

    rule_id: str
    outcome: Outcome
    count: int | None

    def met_by(self, violations: Sequence[Violation]) -> bool:
        reported = [violation for violation in violations if violation.rule_id == self.rule_id]
        if self.outcome == "success":
            return not reported
        severity = Severity.FATAL if self.outcome == "error" else Severity.WARNING
        matching = sum(1 for violation in reported if violation.severity is severity)
        return matching == self.count if self.count is not None else matching > 0


@dataclass(frozen=True)
class Case:
    """One ``test`` of a published ``testSet``: a document and its expectations."""

    description: str
    document: etree._ElementTree
    expectations: tuple[Expectation, ...]


def _expectation(element: etree._Element) -> Expectation | None:
    if not isinstance(element.tag, str):
        return None
    outcome = _OUTCOMES.get(etree.QName(element).localname)
    if outcome is None:
        return None
    number = element.get("number")
    count = int(number) if number is not None and outcome != "success" else None
    return Expectation(rule_id=(element.text or "").strip(), outcome=outcome, count=count)


def _cases(path: Path) -> list[Case]:
    cases = []
    for test in load_document(path).getroot().iterfind(f"{{{VEFA}}}test"):
        assertion = test.find(f"{{{VEFA}}}assert")
        assert assertion is not None, f"{path.name}: a test without an assert element"
        (document,) = (
            child for child in test if isinstance(child.tag, str) and child is not assertion
        )
        expectations = tuple(
            expectation for element in assertion if (expectation := _expectation(element))
        )
        cases.append(
            Case(
                description=" ".join(assertion.findtext(f"{{{VEFA}}}description", "").split()),
                document=etree.ElementTree(copy.deepcopy(document)),
                expectations=expectations,
            )
        )
    return cases


def _unmet(validator: SchematronValidator, path: Path) -> list[str]:
    """The published expectations of one test set that the validator does not meet."""
    failures = []
    for case in _cases(path):
        violations = validator.validate(case.document)
        for expectation in case.expectations:
            if not expectation.met_by(violations):
                reported = sorted(
                    f"{violation.severity}"
                    for violation in violations
                    if violation.rule_id == expectation.rule_id
                )
                failures.append(f"{case.description!r}: expected {expectation}, got {reported}")
    return failures


def _describe(violations: Sequence[Violation]) -> str:
    return "\n".join(f"{v.rule_id} {v.severity} {v.xpath}: {v.message}" for v in violations)


def _relative(path: Path) -> str:
    return f"{path.parent.name}/{path.name}"


def test_the_published_unit_tests_are_present() -> None:
    assert CEN_UNIT_TESTS
    assert CEN_EXAMPLES


# --- the published unit tests -----------------------------------------------------------


@pytest.mark.parametrize("path", CEN_UNIT_TESTS, ids=_relative)
def test_en16931_meets_the_published_unit_tests(path: Path) -> None:
    failures = _unmet(schematron.default_validator("en16931"), path)

    assert not failures, "\n".join(failures)


# --- official examples and our synthetic fixtures -------------------------------------


@pytest.mark.parametrize("path", CEN_EXAMPLES, ids=lambda path: path.name)
def test_the_cen_examples_have_no_fatal_violations(path: Path) -> None:
    violations = schematron.default_validator("en16931").validate(load_document(path))

    assert is_valid(violations), _describe(violations)


@pytest.mark.parametrize("path", SYNTHETIC_FIXTURES, ids=lambda path: path.name)
def test_the_synthetic_fixtures_satisfy_en16931(path: Path) -> None:
    violations = schematron.default_validator("en16931").validate(load_document(path))

    assert violations == (), _describe(violations)


_NAMESPACES = {
    "ubl": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
}


@pytest.mark.parametrize(
    ("edited", "attribute", "value", "rule_id", "xpath"),
    [
        # The context of BR-CO-15 is the invoice itself: it compares the document totals.
        (
            "/ubl:Invoice/cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount",
            None,
            "1.00",
            "BR-CO-15",
            "/ubl:Invoice",
        ),
        # The context of BR-CL-23 is the quantity whose unit code is not in UN/ECE Rec. 20/21.
        (
            "/ubl:Invoice/cac:InvoiceLine/cbc:InvoicedQuantity",
            "unitCode",
            "NOT-A-UNIT",
            "BR-CL-23",
            "/ubl:Invoice/cac:InvoiceLine/cbc:InvoicedQuantity",
        ),
    ],
    ids=["document-rule", "element-rule"],
)
def test_violations_point_at_the_rule_context(
    edited: str, attribute: str | None, value: str, rule_id: str, xpath: str
) -> None:
    tree = load_document(SYNTHETIC_DIR / "srb-minimal-invoice.xml")
    (element,) = tree.xpath(edited, namespaces=_NAMESPACES)
    if attribute:
        element.set(attribute, value)
    else:
        element.text = value
    (context,) = tree.xpath(xpath, namespaces=_NAMESPACES)

    violations = schematron.default_validator("en16931").validate(tree)

    assert [(v.severity, v.xpath, v.line) for v in violations if v.rule_id == rule_id] == [
        (Severity.FATAL, xpath, context.sourceline)
    ]


# --- performance ------------------------------------------------------------------------


def test_warm_validation_stays_within_the_performance_budget() -> None:
    """Brief §5: validating a typical invoice takes < 500 ms warm, all layers together."""
    tree = load_document(SYNTHETIC_DIR / "srb-minimal-invoice.xml")
    validator = schematron.default_validator("en16931")  # compiled outside the measurement
    durations = []
    for _ in range(10):
        start = time.perf_counter()
        validator.validate(tree)
        durations.append(time.perf_counter() - start)

    assert statistics.median(durations) < 0.25  # half of the budget for the costliest layer
