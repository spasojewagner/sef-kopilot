"""The SRB-CIUS rule set as a whole: identity, sources, tests per rule, valid fixtures."""

from __future__ import annotations

import ast
import re
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from einvoice_core import srb
from einvoice_core.srb import RULES, SOURCES, validate_srb
from einvoice_core.srb import rules as rules_package
from einvoice_core.srb.rule import Document
from einvoice_core.srb.rules import load_rules
from einvoice_core.ubl import build_invoice
from einvoice_core.xml import load_document

TESTS = Path(__file__).parent
TERM = re.compile(r"B[GT]-E?\d+")


def test_rule_identifiers_are_sequential() -> None:
    assert [rule.id for rule in RULES] == [f"SRB-{n:03d}" for n in range(1, len(RULES) + 1)]


@pytest.mark.parametrize("rule", RULES, ids=[rule.id for rule in RULES])
def test_every_rule_is_described_and_sourced(rule: srb.Rule) -> None:
    assert rule.title
    assert not rule.title.endswith(".")
    assert rule.terms
    assert all(TERM.fullmatch(term) for term in rule.terms)
    assert rule.references
    assert all(reference.document in SOURCES for reference in rule.references)


@pytest.mark.parametrize("rule", RULES, ids=[rule.id for rule in RULES])
def test_every_rule_has_tests_that_satisfy_and_break_it(rule: srb.Rule) -> None:
    number = rule.id.removeprefix("SRB-")
    (module,) = TESTS.glob(f"test_srb_{number}_*.py")
    names = [
        node.name
        for node in ast.parse(module.read_text(encoding="utf-8")).body
        if isinstance(node, ast.FunctionDef)
    ]

    assert any(name.startswith("test_satisfied_") for name in names), module.name
    assert any(name.startswith("test_broken_") for name in names), module.name


def test_the_core_readme_lists_every_rule() -> None:
    readme = (TESTS.parents[1] / "README.md").read_text(encoding="utf-8")
    listed = [line for line in readme.splitlines() if line.startswith("| SRB-")]

    assert listed == [
        f"| {rule.id} | {rule.title} | {', '.join(rule.terms)} | {rule.severity} |"
        for rule in RULES
    ]


def test_the_synthetic_serbian_invoices_satisfy_every_rule(synthetic_dir: Path) -> None:
    for path in sorted(synthetic_dir.glob("srb-*.xml")):
        assert validate_srb(load_document(path)) == (), path.name


# --- the document view -----------------------------------------------------------------------


def test_the_document_view_finds_elements_and_nothing_else(synthetic_dir: Path) -> None:
    tree = load_document(synthetic_dir / "srb-minimal-invoice.xml")
    document = Document(tree=tree, invoice=build_invoice(tree.getroot()))
    seller = document.find("cac:AccountingSupplierParty/cac:Party")

    assert seller is not None
    assert document.find("cbc:EndpointID", seller) is seller[0]
    assert document.find("cac:PayeeParty") is None
    assert document.find_all("count(cac:InvoiceLine)") == []
    assert document.find_all("cbc:ID/text()") == []


# --- loading rules ---------------------------------------------------------------------------


@pytest.fixture
def extra_rule_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A directory searched for rule modules besides the real ones."""
    monkeypatch.setattr(rules_package, "__path__", [*rules_package.__path__, str(tmp_path)])
    yield tmp_path
    for name in [
        name for name in sys.modules if name.startswith(f"{rules_package.__name__}.srb_9")
    ]:
        del sys.modules[name]


def test_a_rule_module_without_a_rule_is_refused(extra_rule_module: Path) -> None:
    (extra_rule_module / "srb_998_empty.py").write_text("X = 1\n", encoding="utf-8")

    with pytest.raises(TypeError, match="srb_998_empty does not define RULE"):
        load_rules()


def test_a_rule_whose_identifier_differs_from_its_module_is_refused(
    extra_rule_module: Path,
) -> None:
    source = (
        "from einvoice_core.srb.rule import Reference, Rule\n"
        "RULE = Rule(id='SRB-001', title='Copied', terms=('BT-1',),\n"
        "            references=(Reference('srb-cius', '1.3'),), check=lambda document: ())\n"
    )
    (extra_rule_module / "srb_997_copy.py").write_text(source, encoding="utf-8")

    with pytest.raises(ValueError, match="srb_997_copy defines SRB-001, expected SRB-997"):
        load_rules()


def test_other_modules_are_ignored(extra_rule_module: Path) -> None:
    (extra_rule_module / "helpers.py").write_text("raise RuntimeError\n", encoding="utf-8")

    assert load_rules() == RULES
