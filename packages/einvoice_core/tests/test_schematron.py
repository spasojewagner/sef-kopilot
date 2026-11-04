"""The Schematron runner: Saxon integration, SVRL mapping, the compile pipeline and its cache.

These tests run small stylesheets written here, in a temporary rule-set directory, so that
every branch of the runner is exercised in isolation and quickly. Conformance with the
official rule sets and their published unit tests is in ``test_schematron_conformance.py``.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from lxml import etree
from saxonche import PySaxonApiError

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
    assert rule_set.is_source is (path.suffix == ".sch")


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


def test_saxon_warnings_never_reach_the_standard_error_stream(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    """A dynamic error in a match pattern is a warning quoting the value it met; the shape is
    one the Peppol rules meet when a party has two VAT identifiers."""
    two_notes = f"""<Invoice xmlns="{UBL}" xmlns:cbc="{CBC}">
  <cbc:Note>quoted-from-the-invoice</cbc:Note><cbc:Note>second</cbc:Note>
</Invoice>"""
    warning = _stylesheet(
        globals_='<xsl:variable name="notes" select="//cbc:Note/string()"/>'
        '<xsl:template match="cbc:Note[$notes]"/>'
    ).replace(
        "<svrl:schematron-output>",
        "<svrl:schematron-output><xsl:apply-templates select='//cbc:Note'/>",
    )
    validator = _validator(tmp_path, warning)

    assert validator.validate(_invoice(two_notes)) == ()

    captured = capfd.readouterr()
    assert "quoted-from-the-invoice" not in captured.err + captured.out
    assert captured.err == ""


#: Run in a process of its own, whose null device is a file that cannot be opened: Saxon reads
#: the configuration once per process.
WITHOUT_A_NULL_DEVICE = """
import os
import sys

os.devnull = sys.argv[1]
from einvoice_core import schematron

executable = schematron._xslt_processor().compile_stylesheet(stylesheet_text=sys.argv[2])
print(executable.transform_to_string(xdm_node=schematron._processor().parse_xml(xml_text="<a/>")))
"""


def test_without_a_null_device_saxon_still_transforms_and_says_where_its_warnings_go(
    tmp_path: Path,
) -> None:
    stylesheet = (
        '<xsl:stylesheet version="2.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">'
        '<xsl:output method="text"/><xsl:template match="/">transformed</xsl:template>'
        "</xsl:stylesheet>"
    )
    missing = tmp_path / "missing" / "null"

    finished = subprocess.run(
        [sys.executable, "-c", WITHOUT_A_NULL_DEVICE, str(missing), stylesheet],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert (finished.returncode, finished.stdout) == (0, "transformed\n"), finished.stderr
    assert f"Saxon cannot send its standard error to {missing}" in finished.stderr
    assert list(tmp_path.iterdir()) == []


def test_a_refused_configuration_is_followed_by_a_processor_without_one(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    made: list[list[str]] = []
    plain = object()

    def processor(**options: object) -> object:
        made.append(sorted(options))
        if "config_file" in options:
            raise PySaxonApiError("Invalid configuration property")
        return plain

    monkeypatch.setattr(schematron, "PySaxonProcessor", processor)

    assert schematron._processor.__wrapped__() is plain
    assert made == [["config_file", "license"], ["license"]]
    assert "its warnings, which can quote a document, will reach" in caplog.text


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


# --- compiling Schematron sources, with the cache ---------------------------------------

# A stand-in for the ISO pipeline with the same three steps: the first resolves includes
# against the source's directory, the second marks the schema as expanded, the third writes a
# stylesheet whose messages show what the earlier steps and the parameters did.
FAKE_COMPILER = {
    "iso_dsdl_include.xsl": """<xsl:stylesheet version="2.0"
    xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:template match="@* | node()">
    <xsl:copy><xsl:apply-templates select="@* | node()"/></xsl:copy>
  </xsl:template>
  <xsl:template match="include"><xsl:apply-templates select="document(@href, .)/*"/></xsl:template>
</xsl:stylesheet>""",
    "iso_abstract_expand.xsl": """<xsl:stylesheet version="2.0"
    xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:template match="@* | node()">
    <xsl:copy><xsl:apply-templates select="@* | node()"/></xsl:copy>
  </xsl:template>
  <xsl:template match="/*">
    <xsl:copy><xsl:attribute name="expanded" select="'yes'"/><xsl:apply-templates/></xsl:copy>
  </xsl:template>
</xsl:stylesheet>""",
    "iso_svrl_for_xslt2.xsl": """<xsl:stylesheet version="2.0"
    xmlns:xsl="http://www.w3.org/1999/XSL/Transform" xmlns:axsl="urn:example:alias"
    xmlns:svrl="http://purl.oclc.org/dsdl/svrl">
  <xsl:namespace-alias stylesheet-prefix="axsl" result-prefix="xsl"/>
  <xsl:param name="allow-foreign" select="'false'"/>
  <xsl:param name="generate-fired-rule" select="'true'"/>
  <xsl:template match="/">
    <axsl:stylesheet version="2.0">
      <axsl:template match="/">
        <svrl:schematron-output>
          <xsl:for-each select="//rule">
            <svrl:failed-assert id="{@id}" flag="fatal" location="{@location}">
              <svrl:text><xsl:value-of select="@message,
                concat('expanded=', /*/@expanded),
                concat('allow-foreign=', $allow-foreign),
                concat('generate-fired-rule=', $generate-fired-rule)"/></svrl:text>
            </svrl:failed-assert>
          </xsl:for-each>
        </svrl:schematron-output>
      </axsl:template>
    </axsl:stylesheet>
  </xsl:template>
</xsl:stylesheet>""",
    "iso_schematron_skeleton_for_saxon.xsl": "<!-- imported by the real generator -->",
}
COMPILER_PREFIX = "trunk/schematron/code/"


def _source_package(root: Path, message: str = "Included rule") -> RuleSet:
    _package(
        root,
        schematron.COMPILER_PACKAGE,
        {COMPILER_PREFIX + n: t for n, t in FAKE_COMPILER.items()},
    )
    _package(
        root,
        "pkg",
        {
            "sch/main.sch": '<schema><include href="parts/rule.sch"/></schema>',
            "sch/parts/rule.sch": f'<rule id="FAKE-1" location="{ROOT_STEP}" message="{message}"/>',
        },
    )
    return RuleSet(name="fake", package="pkg", path="sch/main.sch", description="Compiled.")


def _cached(root: Path) -> list[Path]:
    return sorted((root / schematron.CACHE_DIR).glob("*"))


def test_sources_are_compiled_with_the_three_step_pipeline(tmp_path: Path) -> None:
    rule_set = _source_package(tmp_path)

    (violation,) = SchematronValidator(rule_set, root=tmp_path).validate(_invoice())

    assert violation.rule_id == "FAKE-1"
    assert violation.message == (
        "Included rule expanded=yes allow-foreign=true generate-fired-rule=false"
    )
    assert violation.xpath == "/ubl:Invoice"


def test_compiled_sources_are_cached_and_the_cache_is_used(tmp_path: Path) -> None:
    rule_set = _source_package(tmp_path)
    SchematronValidator(rule_set, root=tmp_path)
    (cached,) = _cached(tmp_path)
    assert cached.name.startswith("fake-")
    assert cached.suffix == ".xslt"
    cached.write_text(_stylesheet(_failed(ROOT_STEP, "FROM-CACHE")), encoding="utf-8")

    (violation,) = SchematronValidator(rule_set, root=tmp_path).validate(_invoice())

    assert violation.rule_id == "FROM-CACHE"


def test_a_changed_source_is_compiled_again(tmp_path: Path) -> None:
    rule_set = _source_package(tmp_path, message="First")
    SchematronValidator(rule_set, root=tmp_path)
    _source_package(tmp_path, message="Second")

    (violation,) = SchematronValidator(rule_set, root=tmp_path).validate(_invoice())

    assert violation.message.startswith("Second ")
    assert len(_cached(tmp_path)) == 2


def test_a_changed_compiler_invalidates_the_cache(tmp_path: Path) -> None:
    rule_set = _source_package(tmp_path)
    SchematronValidator(rule_set, root=tmp_path)
    skeleton = ruleset_path(schematron.COMPILER_PACKAGE, root=tmp_path) / (
        COMPILER_PREFIX + "iso_schematron_skeleton_for_saxon.xsl"
    )
    skeleton.write_text("<!-- a new release of the skeleton -->", encoding="utf-8")

    SchematronValidator(rule_set, root=tmp_path)

    assert len(_cached(tmp_path)) == 2


def test_an_unwritable_cache_is_not_an_error(tmp_path: Path) -> None:
    rule_set = _source_package(tmp_path)
    (tmp_path / schematron.CACHE_DIR).write_text("not a directory", encoding="utf-8")

    (violation,) = SchematronValidator(rule_set, root=tmp_path).validate(_invoice())

    assert violation.rule_id == "FAKE-1"


def test_the_cache_holds_no_partial_files(tmp_path: Path) -> None:
    SchematronValidator(_source_package(tmp_path), root=tmp_path)

    assert [path.suffix for path in _cached(tmp_path)] == [".xslt"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX file permissions")
def test_cached_stylesheets_are_readable_by_other_users(tmp_path: Path) -> None:
    """A cache written while building an image must be readable by the service's user."""
    SchematronValidator(_source_package(tmp_path), root=tmp_path)

    (cached,) = _cached(tmp_path)
    assert stat.S_IMODE(cached.stat().st_mode) == 0o644


def test_compile_schematron_returns_the_generated_stylesheet(tmp_path: Path) -> None:
    rule_set = _source_package(tmp_path)
    source = ruleset_path("pkg", root=tmp_path) / rule_set.path
    compiler = ruleset_path(schematron.COMPILER_PACKAGE, root=tmp_path) / COMPILER_PREFIX

    text = schematron.compile_schematron(source, compiler)

    assert text.lstrip().startswith("<?xml")
    assert 'id="FAKE-1"' in text


def test_a_source_that_does_not_compile_is_reported(tmp_path: Path) -> None:
    rule_set = _source_package(tmp_path)
    (ruleset_path("pkg", root=tmp_path) / rule_set.path).write_text("<schema>", encoding="utf-8")

    with pytest.raises(SchematronError, match=r"cannot compile Schematron .*main\.sch"):
        SchematronValidator(rule_set, root=tmp_path)


def test_a_source_that_compiles_to_nothing_is_reported(tmp_path: Path) -> None:
    rule_set = _source_package(tmp_path)
    compiler = ruleset_path(schematron.COMPILER_PACKAGE, root=tmp_path) / COMPILER_PREFIX
    (compiler / "iso_dsdl_include.xsl").write_text(
        '<xsl:stylesheet version="2.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">'
        '<xsl:output method="text"/><xsl:template match="/"/></xsl:stylesheet>',
        encoding="utf-8",
    )

    with pytest.raises(SchematronError, match="produced no stylesheet"):
        SchematronValidator(rule_set, root=tmp_path)


def test_sources_need_the_compiler_package(tmp_path: Path) -> None:
    _package(tmp_path, "pkg", {"main.sch": "<schema/>"})
    rule_set = RuleSet(name="fake", package="pkg", path="main.sch", description="No compiler.")

    with pytest.raises(RulesetNotFoundError, match=schematron.COMPILER_PACKAGE):
        SchematronValidator(rule_set, root=tmp_path)


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
