"""The fixture corpus: the Ministry's SEF examples, the mutations, the recorded verdicts."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest
from lxml import etree

import make_fixtures
from einvoice_core import schematron
from einvoice_core.pipeline import validate
from einvoice_core.rulesets import RulesetNotFoundError, ruleset_path
from einvoice_core.violations import Severity
from einvoice_core.xml import load_document

from .conftest import REPOSITORY_ROOT

SEF_DIR = REPOSITORY_ROOT / "fixtures" / "invoices" / "official" / "sef"
SEF_MANIFEST: dict[str, Any] = json.loads((SEF_DIR / "manifest.json").read_text(encoding="utf-8"))
SEF_EXAMPLES: list[dict[str, Any]] = SEF_MANIFEST["documents"]

VERDICTS: dict[str, dict[str, Any]] = json.loads(
    (REPOSITORY_ROOT / make_fixtures.VERDICTS).read_text(encoding="utf-8")
)["documents"]

#: The documents of the corpus that can be read: the others are refused before any value is.
READABLE = sorted(
    document
    for document, profiles in VERDICTS.items()
    if not any("XML" in verdict["fatal"] for verdict in profiles.values())
)

#: The examples' placeholder PIBs, and the same serial numbers with their valid check digits.
PLACEHOLDER_PIBS = {b"123456789": b"123456788", b"987654321": b"987654328"}

#: What is still wrong once the PIBs are valid: an allowance without a reason, and an
#: attachment whose content the Ministry abbreviated to "...", which is not base64.
GENUINE_PROBLEMS = {
    "faktura-sa-popustom.xml": ["BR-33", "BR-CO-21"],
    "faktura-sa-prilogom.xml": ["XSD"],
}


def _fetched() -> bool:
    try:
        for package in ("ubl-2.1", "en16931", "peppol-bis-billing-3", schematron.COMPILER_PACKAGE):
            ruleset_path(package)
    except RulesetNotFoundError:
        return False
    return True


needs_rule_sets = pytest.mark.skipif(not _fetched(), reason="rule sets not fetched")


def test_the_manifest_lists_every_sef_example_once_in_order() -> None:
    names = [entry["file"] for entry in SEF_EXAMPLES]

    assert names == sorted(set(names))
    assert names == sorted(path.name for path in SEF_DIR.glob("*.xml"))
    assert len(names) == 17


@pytest.mark.parametrize("entry", SEF_EXAMPLES, ids=lambda entry: entry["file"])
def test_each_sef_example_is_the_published_file(entry: dict[str, Any]) -> None:
    data = (SEF_DIR / entry["file"]).read_bytes()

    assert len(data) == entry["bytes"]
    assert hashlib.sha256(data).hexdigest() == entry["sha256"]
    assert entry["url"].startswith("https://www.efaktura.gov.rs/extfile/sr/")
    assert load_document(data).getroot() is not None


@needs_rule_sets
@pytest.mark.parametrize("entry", SEF_EXAMPLES, ids=lambda entry: entry["file"])
def test_the_sef_examples_are_valid_once_their_pibs_are(entry: dict[str, Any]) -> None:
    source = (SEF_DIR / entry["file"]).read_bytes()
    for placeholder, pib in PLACEHOLDER_PIBS.items():
        source = source.replace(placeholder, pib)

    report = validate(source, "srb")

    fatal = sorted(v.rule_id for v in report.violations if v.severity is Severity.FATAL)
    warnings = {v.rule_id for v in report.violations if v.severity is not Severity.FATAL}
    assert fatal == GENUINE_PROBLEMS.get(entry["file"], [])
    assert warnings <= {"SRB-013", "SRB-017", "SRB-023", "SRB-029"}


@needs_rule_sets
@pytest.mark.parametrize("mutation", make_fixtures.MUTATIONS, ids=lambda mutation: mutation.name)
def test_each_mutation_is_reported_as_its_header_says(mutation: make_fixtures.Mutation) -> None:
    report = validate((REPOSITORY_ROOT / mutation.file).read_bytes(), "srb")

    assert sorted(v.rule_id for v in report.violations) == sorted(mutation.expect)


@needs_rule_sets
def test_the_verdicts_cover_the_whole_corpus() -> None:
    recorded = {document: tuple(profiles) for document, profiles in VERDICTS.items()}

    assert recorded == make_fixtures.corpus(), "run `make fixtures`"


@needs_rule_sets
@pytest.mark.parametrize("document", sorted(VERDICTS))
def test_the_verdicts_on_the_corpus_are_unchanged(document: str) -> None:
    for profile, expected in VERDICTS[document].items():
        assert make_fixtures.judge(REPOSITORY_ROOT, document, profile) == expected, (
            f"the {profile} verdict on {document} changed: run `make fixtures`, review the diff"
        )


def _a_comment_inside_every_value(source: bytes) -> bytes:
    """``source`` with a comment or a processing instruction in the middle of every value."""
    root = etree.fromstring(source, etree.XMLParser(resolve_entities=False))
    values = [
        element
        for element in root.iter()
        if isinstance(element.tag, str)
        and len(element) == 0
        and len((element.text or "").strip()) > 1
    ]
    for number, element in enumerate(values):
        text = element.text or ""
        middle = len(text) // 2
        mark = etree.Comment(" a note ") if number % 2 else etree.ProcessingInstruction("note")
        element.text, mark.tail = text[:middle], text[middle:]
        element.append(mark)
    return etree.tostring(root.getroottree(), xml_declaration=True, encoding="UTF-8")


@needs_rule_sets
@pytest.mark.parametrize("document", READABLE)
def test_a_comment_inside_every_value_changes_no_verdict(document: str) -> None:
    """XML lets a comment sit inside a value: ``1<!-- -->2000.00`` is the amount ``12000.00``.

    Read as two text nodes, the value was ``1`` to the model and to the SRB rules, so the
    arithmetic reported totals that do not add up, and the Peppol rules that read ``text()``
    stopped with an error.
    """
    source = _a_comment_inside_every_value((REPOSITORY_ROOT / document).read_bytes())

    for profile, expected in VERDICTS[document].items():
        report = validate(source, profile, max_violations=100_000)
        assert make_fixtures.verdict(report) == expected, profile
