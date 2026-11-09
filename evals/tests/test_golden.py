"""The golden set: its file, the cases it names, and the rules read from a mutation's header."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from sef_evals.golden import GoldenError, load_cases, reported_in_header

from .conftest import REPOSITORY_ROOT

GOLDEN = REPOSITORY_ROOT / "evals" / "golden" / "documents.yaml"
VERDICTS = REPOSITORY_ROOT / "fixtures" / "invoices" / "verdicts.json"


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("The srb profile reports: SRB-009 (2).", {"SRB-009": 2}),
        ("The srb profile reports: XSD.", {"XSD": 1}),
        ("The srb profile reports: BR-CO-10, BR-CO-13.", {"BR-CO-10": 1, "BR-CO-13": 1}),
        ("The srb profile reports: BR-CO-17, SRB-021 (3).", {"BR-CO-17": 1, "SRB-021": 3}),
    ],
)
def test_reads_the_rules_a_header_states(line: str, expected: dict[str, int]) -> None:
    header = f'<?xml version="1.0"?>\n<!--\n  Mistake: something.\n  {line}\n-->\n<Invoice/>'
    assert reported_in_header(header) == Counter(expected)


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("<Invoice/>", "no line 'The srb profile reports"),
        ("<!-- The srb profile reports: SRB-009 (two). -->", "cannot read 'SRB-009 (two)'"),
        ("<!-- The srb profile reports: srb-009. -->", "cannot read 'srb-009'"),
        ("<!-- The srb profile reports: SRB-009 (0). -->", "cannot read 'SRB-009 (0)'"),
    ],
)
def test_refuses_a_header_it_cannot_read(text: str, problem: str) -> None:
    with pytest.raises(GoldenError, match=problem.replace("(", r"\(").replace(")", r"\)")):
        reported_in_header(text.replace("<!-- ", "<!--\n  ").replace(" -->", "\n-->"))


def test_names_every_document_of_the_corpus() -> None:
    """Every document whose verdict the fixtures record is in the golden set, under one of
    the profiles it is judged by, and nothing else is."""
    cases = load_cases(REPOSITORY_ROOT, GOLDEN)
    recorded = json.loads(VERDICTS.read_text(encoding="utf-8"))["documents"]
    assert {case.document for case in cases} == set(recorded)
    for case in cases:
        assert case.profile in recorded[case.document], case.id


def test_every_mutation_must_be_reported_for_its_mistake() -> None:
    cases = load_cases(REPOSITORY_ROOT, GOLDEN)
    mutations = [case for case in cases if "/mutations/" in case.document]
    assert len(mutations) == 43
    assert all(case.reports for case in mutations)
    assert next(
        case for case in mutations if case.document.endswith("srb-009-pib-check-digit.xml")
    ).reports == Counter({"SRB-009": 2})


def _golden(root: Path, groups: str) -> Path:
    path = root / "documents.yaml"
    path.write_text(f"groups:\n{groups}", encoding="utf-8")
    return path


def _documents(root: Path, *names: str, text: str = "<Invoice/>") -> None:
    for name in names:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")


def test_reads_groups_by_glob_without_the_excluded(tmp_path: Path) -> None:
    _documents(tmp_path, "d/a.xml", "d/b.xml", "d/c.xml")
    path = _golden(
        tmp_path,
        """\
  - name: some
    title: Some
    documents: ["d/*.xml", d/a.xml]
    exclude: d/b.xml
    profile: srb
    expect: reject
    reports: [SRB-009, SRB-009, BR-01]
  - name: again
    title: The same under another profile
    documents: d/a.xml
    profile: en16931
    expect: accept
""",
    )
    cases = load_cases(tmp_path, path)
    assert [(case.id, case.expect) for case in cases] == [
        ("d/a.xml [srb]", "reject"),
        ("d/c.xml [srb]", "reject"),
        ("d/a.xml [en16931]", "accept"),
    ]
    assert cases[0].reports == Counter({"SRB-009": 2, "BR-01": 1})
    assert cases[0].group == "some"
    assert cases[2].reports == Counter()


@pytest.mark.parametrize(
    ("groups", "problem"),
    [
        (
            "  - {name: one, title: One, documents: d/a.xml, profile: srb, expect: accept}\n"
            "  - {name: two, title: Two, documents: d/a.xml, profile: srb, expect: reject}\n",
            r"group two: d/a.xml \[srb\] is already in another group",
        ),
        (
            "  - {name: one, title: One, documents: d/z*.xml, profile: srb, expect: accept}\n",
            "group one: 'd/z\\*.xml' names no document",
        ),
        (
            "  - {name: one, title: One, documents: d/a.xml, profile: sef, expect: accept}\n",
            "unknown profile 'sef'",
        ),
        (
            "  - {name: one, title: One, documents: d/a.xml, profile: srb, expect: maybe}\n",
            "expect",
        ),
        (
            "  - {name: one, title: One, documents: d/a.xml, profile: srb, expect: accept, "
            "colour: red}\n",
            "colour",
        ),
        (
            "  - {name: One, title: One, documents: d/a.xml, profile: srb, expect: accept}\n",
            "name",
        ),
        (
            "  - {name: one, title: One, documents: d/a.xml, profile: srb, expect: reject, "
            "reports: header}\n",
            "group one: d/a.xml: no line 'The srb profile reports",
        ),
        ("  - {name: one, title: [unclosed\n", "documents.yaml"),
    ],
)
def test_refuses_a_golden_set_it_cannot_trust(tmp_path: Path, groups: str, problem: str) -> None:
    _documents(tmp_path, "d/a.xml")
    with pytest.raises(GoldenError, match=problem):
        load_cases(tmp_path, _golden(tmp_path, groups))


def test_refuses_a_file_without_groups(tmp_path: Path) -> None:
    path = tmp_path / "documents.yaml"
    path.write_text("groups: []\n", encoding="utf-8")
    with pytest.raises(GoldenError, match="groups"):
        load_cases(tmp_path, path)
