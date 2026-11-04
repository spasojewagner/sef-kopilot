"""The validation pipeline: layer order, profiles, set-asides, limits, unreadable documents."""

from __future__ import annotations

import pytest

from einvoice_core import pipeline, schematron
from einvoice_core.pipeline import PROFILES, ValidationReport, validate
from einvoice_core.rulesets import RulesetNotFoundError, ruleset_path
from einvoice_core.xml import ParseError, load_document

from .conftest import SYNTHETIC_DIR, THIRD_PARTY

INVOICE = (SYNTHETIC_DIR / "srb-minimal-invoice.xml").read_text(encoding="utf-8")
CREDIT_NOTE = (SYNTHETIC_DIR / "credit-note-full.xml").read_text(encoding="utf-8")
PEPPOL_EXAMPLE = THIRD_PARTY / "peppol-bis-billing-3" / "rules" / "examples" / "Vat-category-S.xml"
ALL_LAYERS = ("xml", "xsd", "schematron", "srb-cius", "arithmetic")


def _fetched() -> bool:
    try:
        for package in ("ubl-2.1", "en16931", "peppol-bis-billing-3", schematron.COMPILER_PACKAGE):
            ruleset_path(package)
    except RulesetNotFoundError:
        return False
    return True


needs_rule_sets = pytest.mark.skipif(not _fetched(), reason="rule sets not fetched")


def edited(source: str, *edits: tuple[str, str]) -> bytes:
    for old, new in edits:
        assert old in source, old
        source = source.replace(old, new, 1)
    return source.encode("utf-8")


def ran(report: ValidationReport) -> dict[str, bool]:
    return {outcome.layer: outcome.ran for outcome in report.layers}


def rule_ids(report: ValidationReport, layer: str | None = None) -> set[str]:
    return {v.rule_id for v in report.violations if layer is None or v.layer == layer}


def set_aside(report: ValidationReport) -> dict[str, str]:
    return {item.violation.rule_id: item.reason for item in report.set_aside}


# --- without rule sets -----------------------------------------------------------------------


def test_an_unknown_profile_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown profile 'xrechnung'; choose one of srb"):
        validate(INVOICE.encode(), "xrechnung")


def test_a_document_that_is_not_xml_is_reported_not_raised() -> None:
    report = validate(b"<Invoice><cbc:ID>", "srb")

    (violation,) = report.violations
    assert (violation.layer, violation.rule_id, violation.code) == ("xml", "XML", "UNREADABLE")
    assert not report.valid
    assert ran(report) == dict.fromkeys(ALL_LAYERS, False) | {"xml": True}
    assert {o.note for o in report.layers if not o.ran} == {"the document could not be read"}


def test_every_profile_hands_the_calculation_rules_to_the_arithmetic_layer() -> None:
    assert all(pipeline.CALCULATIONS in profile.set_aside for profile in PROFILES.values())


# --- with rule sets --------------------------------------------------------------------------


@needs_rule_sets
def test_the_synthetic_srb_invoice_passes_every_layer() -> None:
    report = validate((SYNTHETIC_DIR / "srb-minimal-invoice.xml").read_bytes(), "srb")

    assert report.valid
    assert report.violations == ()
    assert report.set_aside == ()
    assert ran(report) == dict.fromkeys(ALL_LAYERS, True)
    assert [o.note for o in report.layers if o.layer == "schematron"] == ["en16931"]


@needs_rule_sets
def test_a_loaded_tree_is_accepted_too() -> None:
    tree = load_document(SYNTHETIC_DIR / "srb-minimal-invoice.xml")

    assert validate(tree, "srb").valid


@needs_rule_sets
def test_a_schema_invalid_document_stops_after_the_schema() -> None:
    report = validate(edited(INVOICE, ("<cbc:Note>", "<cbc:Unknown/><cbc:Note>")), "srb")

    assert rule_ids(report) == {"XSD"}
    assert ran(report) == {"xml": True, "xsd": True, "schematron": False, "srb-cius": False,
                           "arithmetic": False}  # fmt: skip
    assert {o.note for o in report.layers if not o.ran} == {"the document is not schema-valid"}


@needs_rule_sets
def test_the_en16931_profile_leaves_the_serbian_rules_out() -> None:
    report = validate(CREDIT_NOTE.encode(), "en16931")

    assert report.valid
    (srb,) = (o for o in report.layers if o.layer == "srb-cius")
    assert not srb.ran
    assert srb.note == "not part of the en16931 profile"


@needs_rule_sets
def test_the_peppol_profile_runs_both_peppol_rule_sets() -> None:
    report = validate(PEPPOL_EXAMPLE.read_bytes(), "peppol")

    assert report.valid
    assert [o.note for o in report.layers if o.layer == "schematron"] == ["en16931-peppol, peppol"]


@needs_rule_sets
def test_the_arithmetic_layer_reports_the_calculation_rules_with_the_amounts() -> None:
    wrong_total = ("14400.00</cbc:TaxInclusiveAmount>", "14400.02</cbc:TaxInclusiveAmount>")

    report = validate(edited(INVOICE, wrong_total), "en16931")

    assert rule_ids(report, "arithmetic") == {"BR-CO-15", "BR-CO-16"}
    assert rule_ids(report, "schematron") == set()
    assert set(set_aside(report)) == {"BR-CO-15", "BR-CO-16"}
    assert "states the expected amount" in set_aside(report)["BR-CO-15"]


@needs_rule_sets
def test_violations_come_in_layer_order() -> None:
    document = edited(
        INVOICE,
        (
            "<cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>",
            "<cbc:InvoiceTypeCode>999</cbc:InvoiceTypeCode>",
        ),
        ("14400.00</cbc:TaxInclusiveAmount>", "14400.02</cbc:TaxInclusiveAmount>"),
    )

    srb = validate(document, "srb")

    assert [(v.layer, v.rule_id) for v in srb.violations] == [
        ("schematron", "BR-CL-01"),
        ("srb-cius", "SRB-001"),
        ("arithmetic", "BR-CO-15"),
        ("arithmetic", "BR-CO-16"),
    ]


@needs_rule_sets
def test_only_so_many_violations_are_listed() -> None:
    wrong_total = ("14400.00</cbc:TaxInclusiveAmount>", "14400.02</cbc:TaxInclusiveAmount>")

    report = validate(edited(INVOICE, wrong_total), "en16931", max_violations=1)

    assert len(report.violations) == 1
    assert report.omitted == 1
    assert not report.valid


@needs_rule_sets
def test_a_schema_valid_document_the_model_cannot_read(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(_root: object) -> None:
        raise ParseError("missing required element cac:Party", xpath="/ubl:Invoice")

    monkeypatch.setattr(pipeline, "build_invoice", refuse)

    report = validate((SYNTHETIC_DIR / "srb-minimal-invoice.xml").read_bytes(), "srb")

    (violation,) = report.violations
    assert (violation.layer, violation.code, violation.xpath) == ("xml", "MODEL", "/ubl:Invoice")
    assert violation.message.startswith("The document is schema-valid but cannot be read")
    assert ran(report) == dict.fromkeys(ALL_LAYERS, True) | {"srb-cius": False, "arithmetic": False}
    assert {o.note for o in report.layers if not o.ran} == {
        "the document could not be read as an invoice"
    }
