"""A repair: patches applied, the invoice validated again, and the difference shown."""

from __future__ import annotations

import pytest
from lxml import etree

from einvoice_core import schematron
from einvoice_core.patches import Patch
from einvoice_core.repair import repair
from einvoice_core.rulesets import RulesetNotFoundError, ruleset_path
from einvoice_core.xml import ParseError, load_document

from .conftest import SYNTHETIC_DIR

MUTATIONS = SYNTHETIC_DIR / "mutations"
MINIMAL = SYNTHETIC_DIR / "srb-minimal-invoice.xml"
BUYER = "/ubl:Invoice/cac:AccountingCustomerParty/cac:Party"
SELLER = "/ubl:Invoice/cac:AccountingSupplierParty/cac:Party"

TYPE_CODE = Patch(
    xpath="/ubl:Invoice/cbc:InvoiceTypeCode",
    op="replace",
    value="380",
    reason="SEF takes the invoice type codes 380, 381, 383 and 386 only",
)
CITY = Patch(
    xpath=f"{BUYER}/cac:PostalAddress/cbc:CityName",
    op="add",
    value="Beograd",
    reason="the buyer's address names no city, which SEF requires",
)


def _fetched() -> bool:
    try:
        for package in ("ubl-2.1", "en16931", schematron.COMPILER_PACKAGE):
            ruleset_path(package)
    except RulesetNotFoundError:
        return False
    return True


needs_rule_sets = pytest.mark.skipif(not _fetched(), reason="rule sets not fetched")


def canonical(document: bytes) -> bytes:
    return etree.tostring(load_document(document), method="c14n")


@needs_rule_sets
@pytest.mark.parametrize(
    ("mutation", "fix"),
    [("srb-001-invoice-type-code.xml", TYPE_CODE), ("srb-015-city.xml", CITY)],
)
def test_a_repair_that_undoes_the_mistake_leaves_the_invoice_valid(
    mutation: str, fix: Patch
) -> None:
    repaired = repair(MUTATIONS / mutation, [fix])

    assert [outcome.status for outcome in repaired.outcomes] == ["applied"]
    assert repaired.changed
    assert repaired.report.valid
    assert repaired.report.violations == ()
    assert canonical(repaired.document) == canonical(MINIMAL.read_bytes())


@needs_rule_sets
def test_the_difference_shows_what_changed_and_the_lines_around_it() -> None:
    repaired = repair(MUTATIONS / "srb-015-city.xml", [CITY])

    assert repaired.diff.splitlines()[2:] == [
        "@@ -52,4 +52,5 @@",
        "       <cac:PostalAddress>",
        "         <cbc:StreetName>Bulevar Ogleda 22</cbc:StreetName>",
        "+        <cbc:CityName>Beograd</cbc:CityName>",
        "         <cbc:PostalZone>11000</cbc:PostalZone>",
        "         <cac:Country>",
    ]
    assert repaired.diff.startswith("--- before\n+++ after\n")


@needs_rule_sets
def test_the_difference_is_read_alike_however_the_invoice_is_written() -> None:
    written = etree.tostring(load_document(MUTATIONS / "srb-001-invoice-type-code.xml"))
    one_line = b"".join(line.strip() for line in written.splitlines())

    repaired = repair(one_line, [TYPE_CODE])

    changed = [line for line in repaired.diff.splitlines()[2:] if line[:1] in "+-"]
    assert changed == [
        "-  <cbc:InvoiceTypeCode>393</cbc:InvoiceTypeCode>",
        "+  <cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>",
    ]
    assert b"\n" not in repaired.document.split(b"?>", 1)[1].strip()  # still on one line


@needs_rule_sets
def test_a_patch_a_person_must_decide_leaves_its_place_and_the_verdict_on_it() -> None:
    pib = Patch(
        xpath=f"{SELLER}/cbc:EndpointID",
        op="replace",
        value="100000024",
        reason="the check digit of 100000025 is wrong",
    )
    note = Patch(xpath="/ubl:Invoice/cbc:Note", op="replace", value="Rok: 15 dana", reason="why")

    repaired = repair(MUTATIONS / "srb-009-pib-check-digit.xml", [pib, note])

    assert [outcome.status for outcome in repaired.outcomes] == ["needs-decision", "applied"]
    assert repaired.changed
    assert [line for line in repaired.diff.splitlines() if line.startswith("+ ")] == [
        "+  <cbc:Note>Rok: 15 dana</cbc:Note>"
    ]
    assert {violation.rule_id for violation in repaired.report.violations} == {"SRB-009"}
    assert not repaired.report.valid


@needs_rule_sets
def test_a_patch_that_writes_what_is_there_changes_nothing() -> None:
    repaired = repair(MINIMAL, [TYPE_CODE])

    (outcome,) = repaired.outcomes
    assert (outcome.status, outcome.before, outcome.after) == ("applied", "380", "380")
    assert (repaired.changed, repaired.diff) == (False, "")


@needs_rule_sets
def test_no_patch_that_applies_is_no_change() -> None:
    repaired = repair(MINIMAL, [])

    assert (repaired.outcomes, repaired.changed, repaired.diff) == ((), False, "")
    assert repaired.report.valid
    assert repaired.document.startswith(b"<?xml version='1.0' encoding='UTF-8'?>\n<Invoice")


@needs_rule_sets
def test_the_patched_invoice_is_judged_under_the_profile_asked_for() -> None:
    repaired = repair(MUTATIONS / "srb-001-invoice-type-code.xml", [], "en16931")

    assert repaired.report.profile == "en16931"
    assert repaired.report.valid  # 393 is a type code EN 16931 knows; only SEF refuses it


def test_an_unknown_profile_is_refused_before_the_invoice_is_read() -> None:
    with pytest.raises(ValueError, match="unknown profile 'xrechnung'; choose one of srb"):
        repair(b"not read", [], "xrechnung")


def test_an_invoice_that_cannot_be_read_cannot_be_patched() -> None:
    with pytest.raises(ParseError, match="malformed XML"):
        repair(b"<Invoice>", [TYPE_CODE])
