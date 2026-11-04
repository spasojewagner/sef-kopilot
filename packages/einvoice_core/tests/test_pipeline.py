"""The validation pipeline: layer order, profiles, set-asides, limits, unreadable documents."""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest
from lxml import etree

from einvoice_core import pipeline, schematron, xml
from einvoice_core.pipeline import PROFILES, SRB_SET_ASIDE, ValidationReport, validate
from einvoice_core.rulesets import RulesetNotFoundError, ruleset_path
from einvoice_core.srb import validate_srb
from einvoice_core.ubl import build_invoice
from einvoice_core.violations import Severity, Violation
from einvoice_core.xml import ParseError, load_document
from einvoice_core.xsd import validate_xsd

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


def replaced_by(report: ValidationReport) -> dict[str, tuple[str, ...]]:
    return {item.violation.rule_id: item.replaced_by for item in report.set_aside}


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


@pytest.mark.parametrize(
    ("xpath", "currency", "expected"),
    [
        ("/ubl:Invoice/cac:TaxTotal[2]/cac:TaxSubtotal/cac:TaxCategory", "EUR", True),
        ("/ubl:Invoice/cac:TaxTotal[1]/cbc:TaxAmount", "EUR", False),
        ("/ubl:Invoice/cac:TaxTotal", "RSD", False),
        ("/ubl:Invoice/cac:TaxTotal[7]", "EUR", False),
        ("/ubl:Invoice/cac:LegalMonetaryTotal", "EUR", False),
        (None, "EUR", False),
    ],
)
def test_a_vat_total_in_another_currency_is_the_rsd_copy(
    xpath: str | None, currency: str, expected: bool
) -> None:
    source = INVOICE.replace(
        ">RSD</cbc:DocumentCurrencyCode>", f">{currency}</cbc:DocumentCurrencyCode>"
    )
    source = source.replace(
        '<cbc:TaxAmount currencyID="RSD">2400.00</cbc:TaxAmount>',
        f'<cbc:TaxAmount currencyID="{currency}">2400.00</cbc:TaxAmount>',
        1,
    )
    source = source.replace(
        "  <cac:LegalMonetaryTotal>",
        '  <cac:TaxTotal><cbc:TaxAmount currencyID="RSD">2400.00</cbc:TaxAmount></cac:TaxTotal>\n'
        "  <cac:LegalMonetaryTotal>",
    )
    root = load_document(source.encode()).getroot()
    violation = Violation(
        rule_id="BR-S-08", severity=Severity.FATAL, message="m", xpath=xpath, layer="schematron"
    )
    rsd_copy = SRB_SET_ASIDE[-1]

    assert rsd_copy.applies_to(violation, root) is expected


def test_the_vat_copy_needs_an_invoice_currency_to_compare_with() -> None:
    root = load_document(
        edited(INVOICE, ("<cbc:DocumentCurrencyCode>RSD</cbc:DocumentCurrencyCode>", ""))
    ).getroot()
    violation = Violation(
        rule_id="BR-S-08",
        severity=Severity.FATAL,
        message="m",
        xpath="/ubl:Invoice/cac:TaxTotal",
        layer="schematron",
    )

    assert not SRB_SET_ASIDE[-1].applies_to(violation, root)


def test_the_building_code_set_aside_needs_a_located_violation() -> None:
    root = load_document(INVOICE.encode()).getroot()
    (building,) = (rule for rule in SRB_SET_ASIDE if rule.rule_ids == frozenset({"BR-S-10"}))
    violation = Violation(
        rule_id="BR-S-10", severity=Severity.FATAL, message="m", xpath=None, layer="schematron"
    )

    assert not building.applies_to(violation, root)


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
    assert replaced_by(report) == {"BR-CO-15": ("BR-CO-15",), "BR-CO-16": ("BR-CO-16",)}


@needs_rule_sets
def test_srb_sets_aside_reverse_charge_at_a_rate_and_serbian_codes() -> None:
    reverse_charge = edited(
        INVOICE,
        ("<cbc:ID>S</cbc:ID>", "<cbc:ID>AE</cbc:ID>"),
        ("<cbc:ID>S</cbc:ID>", "<cbc:ID>AE</cbc:ID>"),
        (
            "<cbc:Percent>20</cbc:Percent>",
            "<cbc:Percent>20</cbc:Percent>"
            "<cbc:TaxExemptionReasonCode>PDV-RS-10-2-1</cbc:TaxExemptionReasonCode>",
        ),
    )

    srb = validate(reverse_charge, "srb")
    en16931 = validate(reverse_charge, "en16931")

    assert srb.valid
    assert set(set_aside(srb)) == {"BR-AE-05", "BR-AE-09", "BR-CL-22"}
    assert replaced_by(srb)["BR-CL-22"] == ("SRB-022", "SRB-023")
    assert rule_ids(en16931, "schematron") == {"BR-AE-05", "BR-AE-09", "BR-CL-22"}


@needs_rule_sets
def test_srb_sets_aside_the_building_code_on_s_only() -> None:
    def with_code(code: str) -> bytes:
        return edited(
            INVOICE,
            (
                "<cbc:Percent>20</cbc:Percent>",
                f"<cbc:Percent>20</cbc:Percent><cbc:TaxExemptionReasonCode>{code}"
                "</cbc:TaxExemptionReasonCode>",
            ),
        )

    building = validate(with_code("PDV-RS-OBJ"), "srb")
    other = validate(with_code("PDV-RS-25-1-1"), "srb")

    assert set(set_aside(building)) == {"BR-CL-22", "BR-S-10"}
    assert "BR-S-10" in rule_ids(other, "schematron")
    assert "SRB-022" in rule_ids(other, "srb-cius")


@needs_rule_sets
def test_srb_sets_aside_what_en16931_says_about_the_serbian_extension() -> None:
    extension = (
        "<ext:UBLExtensions xmlns:ext='urn:oasis:names:specification:ubl:schema:xsd:"
        "CommonExtensionComponents-2'><ext:UBLExtension><ext:ExtensionContent>"
        "<sbt:SrbDtExt xmlns:sbt='http://mfin.gov.rs/srbdt/srbdtext'><sbt:ReducedTotals>"
        "<cac:LegalMonetaryTotal><cbc:TaxExclusiveAmount currencyID='RSD'>0.00"
        "</cbc:TaxExclusiveAmount><cbc:PayableAmount currencyID='RSD'>0.00</cbc:PayableAmount>"
        "</cac:LegalMonetaryTotal></sbt:ReducedTotals></sbt:SrbDtExt>"
        "</ext:ExtensionContent></ext:UBLExtension></ext:UBLExtensions>"
    )
    document = edited(INVOICE, ("  <cbc:CustomizationID>", f"{extension}<cbc:CustomizationID>"))

    srb = validate(document, "srb")
    en16931 = validate(document, "en16931")

    assert {"BR-12", "UBL-CR-001"} <= set(set_aside(srb))
    assert "Serbian extension" in set_aside(srb)["BR-12"]
    assert rule_ids(srb, "schematron") == set()
    assert {"BR-12", "UBL-CR-001"} <= rule_ids(en16931, "schematron")


@needs_rule_sets
def test_srb_sets_aside_reports_about_the_rsd_copy_of_the_breakdown() -> None:
    rsd_copy = edited(
        CREDIT_NOTE,
        (
            '<cbc:TaxAmount currencyID="RSD">21215.20</cbc:TaxAmount>',
            '<cbc:TaxAmount currencyID="RSD">21215.20</cbc:TaxAmount><cac:TaxSubtotal>'
            '<cbc:TaxableAmount currencyID="RSD">106076.00</cbc:TaxableAmount>'
            '<cbc:TaxAmount currencyID="RSD">21215.20</cbc:TaxAmount><cac:TaxCategory>'
            "<cbc:ID>S</cbc:ID><cbc:Percent>20</cbc:Percent><cac:TaxScheme><cbc:ID>VAT</cbc:ID>"
            "</cac:TaxScheme></cac:TaxCategory></cac:TaxSubtotal>",
        ),
    )

    srb = validate(rsd_copy, "srb")
    en16931 = validate(rsd_copy, "en16931")

    assert "BR-S-08" in set_aside(srb)
    assert "RSD copy" in set_aside(srb)["BR-S-08"]
    assert "BR-S-08" in rule_ids(en16931, "schematron")


def lines(count: int, old: str, new: str) -> etree._ElementTree:
    """The minimal invoice with ``count`` copies of its line, each with ``old`` made ``new``."""
    line = re.search(r"<cac:InvoiceLine>.*?</cac:InvoiceLine>", INVOICE, re.DOTALL)
    assert line is not None
    assert old in line[0], old
    return load_document(INVOICE.replace(line[0], line[0].replace(old, new) * count).encode())


#: What each layer addresses on every line once the line is edited, and how to count it.
UNKNOWN_CATEGORY = ("<cbc:ID>S</cbc:ID>", "<cbc:ID>XX</cbc:ID>")
DECIMAL_COMMA = (">12000.00<", ">12000,00<")
LAYERS: dict[str, tuple[tuple[str, str], Callable[[etree._ElementTree], int]]] = {
    "pipeline": (
        UNKNOWN_CATEGORY,
        lambda tree: len(validate(tree, "srb", max_violations=100_000).violations),
    ),
    "xsd": (DECIMAL_COMMA, lambda tree: len(validate_xsd(tree))),
    "schematron": (
        UNKNOWN_CATEGORY,
        lambda tree: len(schematron.validate_schematron(tree, ["en16931"])),
    ),
    "srb-cius": (UNKNOWN_CATEGORY, lambda tree: len(validate_srb(tree))),
    "model": (UNKNOWN_CATEGORY, lambda tree: len(build_invoice(tree.getroot()).lines)),
}


@needs_rule_sets
@pytest.mark.parametrize("layer", LAYERS)
def test_every_layer_reads_the_children_of_an_element_once(
    layer: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each layer addresses all 300 lines, but reads the invoice's children once, not 300 times:
    its entry point opens a sibling index, and the pipeline opens one for all the layers."""
    edit, addressed = LAYERS[layer]
    tree = lines(300, *edit)
    reads: list[int] = []
    real = xml._Children

    def counted(parent: etree._Element) -> xml._Children:
        reads.append(len(parent))
        return real(parent)

    monkeypatch.setattr(xml, "_Children", counted)

    assert addressed(tree) >= 300
    assert sum(reads) < sum(1 for _ in tree.iter())


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
def test_only_so_many_set_aside_violations_are_listed() -> None:
    """Thousands of set-aside reports would make a report of megabytes from a small document."""
    serbian_code = (
        "<cbc:Percent>20</cbc:Percent>",
        "<cbc:Percent>20</cbc:Percent>"
        "<cbc:TaxExemptionReasonCode>PDV-RS-OBJ</cbc:TaxExemptionReasonCode>",
    )

    whole = validate(edited(INVOICE, serbian_code), "srb")
    cut = validate(edited(INVOICE, serbian_code), "srb", max_violations=1)

    assert (len(whole.set_aside), whole.set_aside_omitted) == (2, 0)
    assert cut.set_aside == whole.set_aside[:1]
    assert cut.set_aside_omitted == 1
    assert cut.valid == whole.valid


@needs_rule_sets
@pytest.mark.parametrize("profile", sorted(PROFILES))
def test_an_amount_too_long_to_compute_with_exactly_is_reported_not_raised(profile: str) -> None:
    """``xs:decimal`` has no bound on its digits; the model accepts 28, far beyond any invoice."""
    amount = "1" + "0" * 27 + ".00"
    source = edited(
        INVOICE,
        (
            '<cbc:LineExtensionAmount currencyID="RSD">12000.00</cbc:LineExtensionAmount>\n'
            "    <cac:Item>",
            f'<cbc:LineExtensionAmount currencyID="RSD">{amount}</cbc:LineExtensionAmount>\n'
            "    <cac:Item>",
        ),
    )

    report = validate(source, profile)

    (model,) = (v for v in report.violations if v.code == "MODEL")
    assert model.xpath == "/ubl:Invoice/cac:InvoiceLine/cbc:LineExtensionAmount"
    assert "more than 28 digits" in model.message
    assert not report.valid
    assert not ran(report)["arithmetic"]


@needs_rule_sets
@pytest.mark.parametrize("profile", sorted(PROFILES))
def test_a_comment_cannot_hide_a_wrong_amount(profile: str) -> None:
    """``14400<!-- -->1`` is 144001 to the schema and to CEN's rules. Read up to the comment, it
    was 14400 to the arithmetic layer, which checks CEN's totals in their place, and an invoice
    due ten times its total was valid."""
    hidden = edited(
        INVOICE, (">14400.00</cbc:PayableAmount>", ">14400<!-- -->1</cbc:PayableAmount>")
    )

    report = validate(hidden, profile)

    assert rule_ids(report, "arithmetic") == {"BR-CO-16"}
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
