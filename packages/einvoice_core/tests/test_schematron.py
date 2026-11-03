"""The Schematron runner: Saxon integration and the mapping of SVRL reports to violations.

These tests run small stylesheets written here, in a temporary rule-set directory, so that
every branch of the runner is exercised in isolation and quickly. Conformance with the
official rule sets and their published unit tests is in ``test_schematron_conformance.py``.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from lxml import etree

from einvoice_core import schematron
from einvoice_core.rulesets import ENV_VAR, RulesetNotFoundError, ruleset_path
from einvoice_core.schematron import RuleSet, SchematronError, SchematronValidator
from einvoice_core.violations import Severity
from einvoice_core.xml import load_document

UBL = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"

INVOICE = f"""<Invoice xmlns="{UBL}" xmlns:cac="{CAC}" xmlns:cbc="{CBC}">
  <cbc:ID>INV-1</cbc:ID>
  <cbc:Note xml:lang="sr">Faktura za čćžšđ / Фактура</cbc:Note>
  <cac:InvoiceLine><cbc:ID>1</cbc:ID></cac:InvoiceLine>
  <cac:InvoiceLine>
    <cbc:ID>2</cbc:ID>
    <cbc:LineExtensionAmount currencyID="RSD">10.00</cbc:LineExtensionAmount>
  </cac:InvoiceLine>
</Invoice>
"""

ROOT_STEP = f"/*:Invoice[namespace-uri()='{UBL}'][1]"
NOTE_STEP = f"/*:Note[namespace-uri()='{CBC}'][1]"
LINE_2_STEP = f"/*:InvoiceLine[namespace-uri()='{CAC}'][2]"
AMOUNT_STEP = f"/*:LineExtensionAmount[namespace-uri()='{CBC}'][1]"


def _invoice(text: str = INVOICE) -> etree._ElementTree:
    return load_document(text.encode())


def _stylesheet(*entries: str, globals_: str = "") -> str:
    """An XSLT 2.0 stylesheet that answers every document with an SVRL report of ``entries``."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="2.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
    xmlns:svrl="http://purl.oclc.org/dsdl/svrl" xmlns:cbc="{CBC}">
  {globals_}
  <xsl:template match="/">
    <svrl:schematron-output>{"".join(entries)}</svrl:schematron-output>
  </xsl:template>
</xsl:stylesheet>
"""


def _failed(location: str, rule_id: str = "T-1", flag: str = "fatal", text: str = "Msg") -> str:
    return (
        f'<svrl:failed-assert id="{rule_id}" flag="{flag}" location="{location}">'
        f"<svrl:text>{text}</svrl:text></svrl:failed-assert>"
    )


def _package(root: Path, name: str, files: dict[str, str]) -> Path:
    """A fetched rule-set package as ``rulesets.ruleset_path`` expects it."""
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SOURCE.json").write_text(json.dumps({"name": name}), encoding="utf-8")
    for relative, text in files.items():
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return directory


def _validator(root: Path, stylesheet: str, name: str = "test") -> SchematronValidator:
    _package(root, "pkg", {"rules.xslt": stylesheet})
    rule_set = RuleSet(name=name, package="pkg", path="rules.xslt", description="Test rules.")
    return SchematronValidator(rule_set, root=root)


# --- the published rule sets ------------------------------------------------------------


@pytest.mark.parametrize("rule_set", schematron.RULE_SETS.values(), ids=schematron.RULE_SETS)
def test_every_published_rule_set_is_in_its_fetched_package(rule_set: RuleSet) -> None:
    try:
        path = ruleset_path(rule_set.package) / rule_set.path
    except RulesetNotFoundError:
        pytest.skip(f"{rule_set.package} not fetched (run `make rulesets`)")

    assert path.is_file()


def test_unknown_rule_set_names_are_rejected_with_the_known_names() -> None:
    with pytest.raises(SchematronError, match="unknown rule set 'peppol-2'; known rule sets: en"):
        schematron.default_validator("peppol-2")


# --- SVRL report -> violations ------------------------------------------------------------


def test_failed_asserts_become_violations_in_report_order(tmp_path: Path) -> None:
    validator = _validator(
        tmp_path,
        _stylesheet(
            _failed(ROOT_STEP, "BR-01", "fatal", "[BR-01]-An Invoice shall have a ..."),
            _failed(ROOT_STEP + NOTE_STEP, "BR-02", "warning", "Second"),
        ),
    )

    first, second = validator.validate(_invoice())

    assert first.rule_id == "BR-01"
    assert first.severity is Severity.FATAL
    assert first.layer == "schematron"
    assert first.message == "[BR-01]-An Invoice shall have a ..."
    assert first.xpath == "/ubl:Invoice"
    assert first.line == 1
    assert first.code is None
    assert (second.rule_id, second.severity, second.xpath, second.line) == (
        "BR-02",
        Severity.WARNING,
        "/ubl:Invoice/cbc:Note",
        3,
    )


def test_successful_reports_count_as_violations(tmp_path: Path) -> None:
    report = (
        f'<svrl:successful-report id="R-1" flag="warning" location="{ROOT_STEP}">'
        "<svrl:text>Reported</svrl:text></svrl:successful-report>"
    )

    (violation,) = _validator(tmp_path, _stylesheet(report)).validate(_invoice())

    assert (violation.rule_id, violation.severity) == ("R-1", Severity.WARNING)


def test_missing_flag_is_fatal_and_missing_id_gets_the_generic_rule_id(tmp_path: Path) -> None:
    entry = (
        f'<svrl:failed-assert location="{ROOT_STEP}"><svrl:text>x</svrl:text></svrl:failed-assert>'
    )

    (violation,) = _validator(tmp_path, _stylesheet(entry)).validate(_invoice())

    assert violation.rule_id == schematron.RULE_ID
    assert violation.severity is Severity.FATAL


def test_message_whitespace_is_normalised(tmp_path: Path) -> None:
    text = "\n   [BR-CO-10]-Sum of Invoice line net amount\n      (BT-106) = Σ (BT-131).\n  "

    (violation,) = _validator(tmp_path, _stylesheet(_failed(ROOT_STEP, text=text))).validate(
        _invoice()
    )

    assert violation.message == "[BR-CO-10]-Sum of Invoice line net amount (BT-106) = Σ (BT-131)."


def test_a_report_without_text_has_an_empty_message(tmp_path: Path) -> None:
    entry = f'<svrl:failed-assert id="X" flag="fatal" location="{ROOT_STEP}"/>'

    (violation,) = _validator(tmp_path, _stylesheet(entry)).validate(_invoice())

    assert violation.message == ""


def test_an_empty_report_means_no_violations(tmp_path: Path) -> None:
    assert _validator(tmp_path, _stylesheet()).validate(_invoice()) == ()


# --- SVRL locations -> canonical XPath ----------------------------------------------------


@pytest.mark.parametrize(
    ("location", "xpath", "line"),
    [
        (ROOT_STEP, "/ubl:Invoice", 1),
        (ROOT_STEP + LINE_2_STEP, "/ubl:Invoice/cac:InvoiceLine[2]", 5),
        (
            ROOT_STEP + LINE_2_STEP + AMOUNT_STEP + "/@currencyID",
            "/ubl:Invoice/cac:InvoiceLine[2]/cbc:LineExtensionAmount/@currencyID",
            7,
        ),
        # A namespace-qualified attribute has no canonical path; its element still has a line.
        (
            ROOT_STEP
            + NOTE_STEP
            + "/@*[local-name()='lang' and namespace-uri()='http://www.w3.org/XML/1998/namespace']",
            None,
            3,
        ),
    ],
    ids=["document-element", "repeated-sibling", "attribute", "qualified-attribute"],
)
def test_locations_resolve_to_canonical_xpaths(
    tmp_path: Path, location: str, xpath: str | None, line: int
) -> None:
    (violation,) = _validator(tmp_path, _stylesheet(_failed(location))).validate(_invoice())

    assert (violation.xpath, violation.line) == (xpath, line)


@pytest.mark.parametrize(
    "location",
    [
        "",
        "/",
        "RSD",  # what a generated stylesheet writes for a rule whose context is an attribute
        ROOT_STEP + LINE_2_STEP.replace("[2]", "[3]"),  # no such sibling
        ROOT_STEP + LINE_2_STEP.replace("[2]", "[0]"),
        ROOT_STEP.replace(UBL, CBC),  # wrong namespace
        f"/*:CreditNote[namespace-uri()='{UBL}'][1]",  # wrong document element
        f"{ROOT_STEP}[2]",  # trailing garbage
        ROOT_STEP + "/@schemeID",  # no such attribute
        ROOT_STEP + "/@*[local-name()='lang' and namespace-uri()='urn:other']",
        ROOT_STEP + "/@currencyID" + NOTE_STEP,  # an attribute step must be the last one
        ROOT_STEP + "/text()[1]",
    ],
)
def test_unresolvable_locations_give_no_xpath(tmp_path: Path, location: str) -> None:
    (violation,) = _validator(tmp_path, _stylesheet(_failed(location))).validate(_invoice())

    assert (violation.xpath, violation.line) == (None, None)


def test_locations_in_documents_without_a_namespace(tmp_path: Path) -> None:
    document = load_document(b"<root>\n<item/>\n<item a='1'/>\n</root>")
    validator = _validator(tmp_path, _stylesheet(_failed("/root[1]/item[2]/@a")))

    (violation,) = validator.validate(document)

    assert (violation.xpath, violation.line) == ("/root/item[2]/@a", 3)


# --- what Saxon is given -----------------------------------------------------------------


def test_the_tree_in_memory_is_validated_with_the_document_as_global_context(
    tmp_path: Path,
) -> None:
    """Rules read global variables such as ``$profile``; the repairer validates edited trees."""
    validator = _validator(
        tmp_path,
        _stylesheet(
            _failed(ROOT_STEP, text='<xsl:value-of select="$id"/>'),
            globals_='<xsl:variable name="id" select="/*/cbc:ID"/>',
        ),
    )
    tree = _invoice()
    tree.getroot()[0].text = "EDITED-7"

    (violation,) = validator.validate(tree)

    assert violation.message == "EDITED-7"


def test_non_ascii_text_reaches_the_rules_unchanged(tmp_path: Path) -> None:
    validator = _validator(
        tmp_path, _stylesheet(_failed(ROOT_STEP, text='<xsl:value-of select="/*/cbc:Note"/>'))
    )

    (violation,) = validator.validate(_invoice())

    assert violation.message == "Faktura za čćžšđ / Фактура"


def test_one_validator_can_be_shared_between_threads(tmp_path: Path) -> None:
    validator = _validator(
        tmp_path,
        _stylesheet(
            _failed(ROOT_STEP, text='<xsl:value-of select="$id"/>'),
            globals_='<xsl:variable name="id" select="/*/cbc:ID"/>',
        ),
    )
    documents = [INVOICE.replace("INV-1", f"INV-{number}") for number in range(16)]

    def message(text: str) -> str:
        return validator.validate(load_document(text.encode()))[0].message

    with ThreadPoolExecutor(max_workers=8) as pool:
        messages = list(pool.map(message, documents * 4))

    assert messages == [f"INV-{number}" for number in range(16)] * 4


# --- failures ------------------------------------------------------------------------------


def test_a_missing_rule_set_file_is_reported(tmp_path: Path) -> None:
    _package(tmp_path, "pkg", {})
    rule_set = RuleSet(name="gone", package="pkg", path="rules.xslt", description="Missing.")

    with pytest.raises(SchematronError, match=r"rule set 'gone': .*rules\.xslt does not exist"):
        SchematronValidator(rule_set, root=tmp_path)


def test_a_stylesheet_that_does_not_compile_is_reported(tmp_path: Path) -> None:
    with pytest.raises(SchematronError, match=r"cannot compile the stylesheet of .*rules\.xslt"):
        _validator(tmp_path, "<xsl:stylesheet version='2.0'/>")


def test_a_dynamic_error_in_a_rule_is_reported(tmp_path: Path) -> None:
    failing = _stylesheet().replace(
        "<svrl:schematron-output>", '<svrl:schematron-output><xsl:value-of select="error()"/>'
    )
    validator = _validator(tmp_path, failing)

    with pytest.raises(SchematronError, match="rule set 'test' failed"):
        validator.validate(_invoice())


@pytest.mark.parametrize(
    ("output", "message"),
    [("", "produced no report"), ("not xml", "unreadable SVRL report")],
)
def test_a_report_that_is_not_svrl_is_reported(tmp_path: Path, output: str, message: str) -> None:
    text_output = f"""<xsl:stylesheet version="2.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:output method="text"/>
  <xsl:template match="/">{output}</xsl:template>
</xsl:stylesheet>"""
    validator = _validator(tmp_path, text_output)

    with pytest.raises(SchematronError, match=message):
        validator.validate(_invoice())


# --- the process-wide validators -----------------------------------------------------------


@pytest.fixture
def extra_rule_sets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Two extra named rule sets in a temporary rule-set directory, for the cached helpers."""
    _package(
        tmp_path,
        "pkg",
        {
            "a.xslt": _stylesheet(_failed(ROOT_STEP, "A-1")),
            "b.xslt": _stylesheet(_failed(ROOT_STEP, "B-1"), _failed(ROOT_STEP, "B-2")),
        },
    )
    monkeypatch.setenv(ENV_VAR, str(tmp_path))
    for name in ("test-a", "test-b"):
        rule_set = RuleSet(name=name, package="pkg", path=f"{name[-1]}.xslt", description=name)
        monkeypatch.setitem(schematron.RULE_SETS, name, rule_set)
    schematron.default_validator.cache_clear()
    yield tmp_path
    schematron.default_validator.cache_clear()


@pytest.mark.usefixtures("extra_rule_sets")
def test_validate_schematron_applies_the_rule_sets_in_order() -> None:
    violations = schematron.validate_schematron(_invoice(), ["test-b", "test-a"])

    assert [violation.rule_id for violation in violations] == ["B-1", "B-2", "A-1"]


@pytest.mark.usefixtures("extra_rule_sets")
def test_default_validators_are_compiled_once() -> None:
    assert schematron.default_validator("test-a") is schematron.default_validator("test-a")
