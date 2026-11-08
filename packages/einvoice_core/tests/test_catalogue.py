"""The catalogue of the rules a profile applies, read from the rule sets the validator runs
(ADR-0047), and the search over it."""

from __future__ import annotations

from pathlib import Path

import pytest

from einvoice_core.arithmetic import STATEMENTS
from einvoice_core.catalogue import CatalogueRule, _assertions, catalogue, search
from einvoice_core.pipeline import PROFILES, validate
from einvoice_core.violations import Severity

from .conftest import SYNTHETIC_DIR, official_examples
from .test_pipeline import needs_rule_sets

pytestmark = needs_rule_sets


def by_id(profile: str) -> dict[str, CatalogueRule]:
    return {rule.id: rule for rule in catalogue(profile)}


@pytest.mark.parametrize("profile", sorted(PROFILES))
def test_every_rule_is_listed_once_in_the_order_of_its_id(profile: str) -> None:
    ids = [rule.id for rule in catalogue(profile)]

    assert len(ids) == len(set(ids)) > 900
    assert ids == sorted(ids)
    assert ids.index("BR-02") < ids.index("BR-10") < ids.index("BR-CO-10")


def test_a_published_rule_reads_as_its_violation_states_it() -> None:
    rules = by_id("en16931")

    assert rules["BR-01"] == CatalogueRule(
        id="BR-01",
        layer="schematron",
        severity=Severity.FATAL,
        statement="An Invoice shall have a Specification identifier (BT-24).",
        source="en16931",
        terms=("BT-24",),
    )
    assert rules["UBL-CR-001"].severity is Severity.WARNING
    assert "SRB-001" not in rules


def test_the_calculation_rules_are_the_arithmetic_layers() -> None:
    """Recomputed under CEN's ids (ADR-0007): listed once, as the layer that reports them."""
    for profile in PROFILES:
        rules = by_id(profile)
        for rule_id, statement in STATEMENTS.items():
            assert (rules[rule_id].layer, rules[rule_id].statement) == ("arithmetic", statement)
            assert rules[rule_id].set_aside is None
    assert by_id("srb")["BR-CO-15"].terms == ("BT-112", "BT-109", "BT-110")


def test_the_serbian_profile_lists_its_rules_and_what_it_sets_aside() -> None:
    rules = by_id("srb")

    assert (rules["SRB-009"].layer, rules["SRB-009"].source) == ("srb-cius", "srb-cius")
    assert rules["SRB-009"].statement == (
        "Every nine-digit PIB has a serial number in range and a valid check digit"
    )
    assert rules["SRB-009"].terms[:2] == ("BT-31", "BT-34")
    assert rules["UBL-CR-001"].set_aside == (
        "SRB-CIUS defines its own extension (SrbDtExt) in ext:UBLExtensions"
    )
    assert rules["UBL-CR-001"].replaced_by == ("SRB-029",)
    assert rules["BR-O-05"].set_aside is not None
    # Set aside only in some places of a document: listed as it is.
    assert rules["BR-01"].set_aside is None
    assert not [rule for rule in by_id("en16931").values() if rule.set_aside is not None]


def test_peppol_lists_its_own_rules_and_cens_in_its_bundle() -> None:
    rules = by_id("peppol")

    assert rules["PEPPOL-EN16931-R001"].source == "peppol"
    assert rules["PEPPOL-EN16931-R001"].statement == "Business process MUST be provided."
    assert rules["BR-01"].source == "en16931-peppol"


def test_an_unknown_profile_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown profile 'xrechnung'"):
        catalogue("xrechnung")


@pytest.mark.parametrize("profile", sorted(PROFILES))
def test_every_rule_a_validation_reports_is_in_the_catalogue(profile: str) -> None:
    """What the validator checks and what the catalogue lists are one list."""
    listed = set(by_id(profile))
    documents = [*sorted(SYNTHETIC_DIR.rglob("*.xml")), *official_examples()]
    reported: set[str] = set()
    for document in documents:
        report = validate(document.read_bytes(), profile)
        reported |= {
            violation.rule_id
            for violation in (*report.violations, *(aside.violation for aside in report.set_aside))
            if violation.layer in ("schematron", "srb-cius", "arithmetic")
        }

    assert reported
    assert reported <= listed


def test_a_rule_set_is_read_as_the_validator_reads_its_report(tmp_path: Path) -> None:
    """An assertion with its id and flag as attributes or as ``xsl:attribute``; one without a
    flag is fatal, one without an id is no rule; a report is a rule as an assertion is."""
    written = tmp_path / "rules.xslt"
    written.write_text(
        """<xsl:stylesheet version="2.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
             xmlns:svrl="http://purl.oclc.org/dsdl/svrl"
             xmlns:sch="http://purl.oclc.org/dsdl/schematron">
          <svrl:failed-assert test="x">
            <xsl:attribute name="id">X-1</xsl:attribute>
            <xsl:attribute name="flag">warning</xsl:attribute>
            <xsl:attribute name="location">/</xsl:attribute>
            <svrl:text>[X-1]-Seller name (BT-27)
              is <xsl:value-of select="."/>required.</svrl:text>
          </svrl:failed-assert>
          <sch:report id="X-2" test="y">[X-2] Reported (BG-4).</sch:report>
          <sch:assert test="z">No id.</sch:assert>
        </xsl:stylesheet>""",
        encoding="utf-8",
    )

    rules = list(_assertions(written, "test"))

    assert [(rule.id, rule.severity, rule.statement, rule.terms) for rule in rules] == [
        ("X-1", Severity.WARNING, "Seller name (BT-27) is required.", ("BT-27",)),
        ("X-2", Severity.FATAL, "Reported (BG-4).", ("BG-4",)),
    ]


# --- search --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "first"),
    [
        ("BR-CO-15", ["BR-CO-15"]),
        ("br-co-1", ["BR-CO-10", "BR-CO-11", "BR-CO-12"]),
        ("  SRB-009 ", ["SRB-009"]),
        ("BT-31", ["SRB-007", "SRB-009"]),
        ("PIB check digit", ["SRB-009"]),
        ("specification IDENTIFIER", ["SRB-005", "BR-01"]),
    ],
)
def test_rules_are_found_by_id_then_term_then_words(query: str, first: list[str]) -> None:
    found = [rule.id for rule in search(catalogue("srb"), query)]

    assert found[: len(first)] == first


def test_words_are_found_whatever_their_diacritics_and_case() -> None:
    rule = CatalogueRule(
        id="T-1",
        layer="srb-cius",
        severity=Severity.FATAL,
        statement="Datum prometa ili avansnog plaćanja",
        source="srb-cius",
        terms=(),
    )

    assert search([rule], "PLACANJA datum") == [rule]
    assert search([rule], "plaćanja") == [rule]
    assert search([rule], "placanje") == []


def test_nothing_is_found_for_nothing_and_no_more_than_asked() -> None:
    rules = catalogue("srb")

    assert search(rules, "  ") == []
    assert search(rules, "[]") == []
    assert len(search(rules, "BR", limit=5)) == 5
