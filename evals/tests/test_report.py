"""The report: what it holds, and that the same run writes the same text."""

from __future__ import annotations

import json

from sef_evals.measures import Measure
from sef_evals.report import as_json, as_markdown, versions
from sef_evals.thresholds import Threshold, judge

from .conftest import REPOSITORY_ROOT

MEASURED = {"rule sets": {"en16931": "validation-1.3.17", "ubl-2.1": "sha256:60b80d76394a"}}


def judged() -> list:  # type: ignore[type-arg]
    return judge(
        [
            Measure("agreement", "Same verdict", "share", 3, ()),
            Measure("false_accept_rate", "Accepted", "rate", 4, ("a.xml [srb]: accepted",)),
            Measure("coverage", "Covered", "share", 0, ()),
        ],
        {
            "agreement": Threshold(min=1.0),
            "false_accept_rate": Threshold(max=0.0),
            "repair_success": Threshold(min=0.8),
        },
    )


def test_the_json_report_holds_each_measure_beside_its_threshold() -> None:
    report = json.loads(as_json(judged(), MEASURED))
    assert report["met"] is False
    assert report["measured"] == MEASURED
    assert report["measures"]["agreement"] == {
        "title": "Same verdict",
        "kind": "share",
        "value": 1.0,
        "passed": 3,
        "total": 3,
        "threshold": {"min": 1.0},
        "met": True,
        "failures": [],
    }
    assert report["measures"]["false_accept_rate"]["value"] == 0.25
    assert report["measures"]["false_accept_rate"]["failures"] == ["a.xml [srb]: accepted"]
    assert report["measures"]["coverage"]["value"] is None
    assert report["measures"]["coverage"]["met"] is None
    assert report["measures"]["repair_success"] == {"threshold": {"min": 0.8}, "met": False}


def test_the_markdown_report_is_a_table_and_the_failures() -> None:
    text = as_markdown(judged(), MEASURED)
    assert "Measured with the rule sets en16931 validation-1.3.17, ubl-2.1 sha256:" in text
    assert "| `agreement` | Same verdict | 100.0% (3 of 3) | ≥ 100% | yes |" in text
    assert "| `false_accept_rate` | Accepted | 25.0% (1 of 4) | ≤ 0% | **no** |" in text
    assert "| `coverage` | Covered | not measured | — | — |" in text
    assert "| `repair_success` |  | not measured | ≥ 80% | **no** |" in text
    assert text.endswith("## `false_accept_rate`\n\n- a.xml [srb]: accepted\n")


def test_the_same_measures_write_the_same_text() -> None:
    assert as_json(judged(), MEASURED) == as_json(judged(), MEASURED)
    assert as_markdown(judged(), MEASURED) == as_markdown(judged(), MEASURED)


def test_names_the_pinned_rule_sets() -> None:
    pinned = versions(REPOSITORY_ROOT)["rule sets"]
    assert set(pinned) == {"ubl-2.1", "en16931", "peppol-bis-billing-3", "iso-schematron"}
    assert pinned["ubl-2.1"].startswith("sha256:")
    assert not pinned["en16931"].startswith("sha256:")
