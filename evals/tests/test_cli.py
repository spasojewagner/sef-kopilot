"""``sef-evals``: running the evaluations, writing their report and checking it."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from einvoice_core.rulesets import RulesetNotFoundError
from sef_evals import __version__, verdicts
from sef_evals.cli import EXIT_ERROR, EXIT_MET, EXIT_NOT_MET, find_root, main
from sef_evals.measures import Measure

from .conftest import REPOSITORY_ROOT, needs_rulesets


def run(root: Path, *argv: str) -> tuple[int, str]:
    out = io.StringIO()
    status = main(list(argv), cwd=root, out=out)
    return status, out.getvalue()


def test_finds_the_root_from_below_it(small_root: Path) -> None:
    (small_root / "docs" / "deeper").mkdir()
    assert find_root(small_root / "docs" / "deeper") == small_root
    assert find_root(small_root.parent) is None


def test_says_when_there_is_nothing_to_run(tmp_path: Path) -> None:
    status, out = run(tmp_path)
    assert (status, out) == (EXIT_ERROR, "sef-evals: no evals/thresholds.yaml here or above\n")


@needs_rulesets
def test_writes_the_report_and_passes_a_check_of_it(small_root: Path) -> None:
    status, out = run(small_root)
    assert status == EXIT_MET
    assert (
        "| `false_accept_rate` | Documents that must be rejected, accepted | 0.0% (0 of 1)" in out
    )
    reports = small_root / "evals" / "reports"
    assert (reports / "latest.md").read_text(encoding="utf-8") == out
    report = json.loads((reports / "latest.json").read_text(encoding="utf-8"))
    assert report["met"] is True
    assert list(report["measures"]) == [
        "agreement",
        "rule_agreement",
        "false_accept_rate",
        "false_reject_rate",
        "detection",
    ]
    assert run(small_root, "--check")[0] == EXIT_MET


@needs_rulesets
def test_a_check_fails_on_a_stale_report_and_writes_nothing(small_root: Path) -> None:
    run(small_root)
    written = small_root / "evals" / "reports" / "latest.json"
    written.write_text("{}\n", encoding="utf-8")
    status, out = run(small_root, "--check")
    assert status == EXIT_NOT_MET
    assert out.endswith(
        "\nsef-evals: the report is stale, run `make evals`: evals/reports/latest.json\n"
    )
    assert written.read_text(encoding="utf-8") == "{}\n"
    (small_root / "evals" / "reports" / "latest.md").unlink()
    assert run(small_root, "--check")[1].endswith(
        "run `make evals`: evals/reports/latest.json, evals/reports/latest.md\n"
    )


@needs_rulesets
def test_a_check_says_both_when_the_report_is_stale_and_a_threshold_not_met(
    small_root: Path,
) -> None:
    run(small_root)
    golden = small_root / "evals" / "golden" / "documents.yaml"
    golden.write_text(
        golden.read_text(encoding="utf-8").replace("expect: accept", "expect: reject"),
        encoding="utf-8",
    )
    status, out = run(small_root, "--check")
    assert status == EXIT_NOT_MET
    assert out.endswith(
        "\nsef-evals: the report is stale, run `make evals`: evals/reports/latest.json, "
        "evals/reports/latest.md\n\nsef-evals: a threshold is not met\n"
    )


@needs_rulesets
def test_fails_when_a_threshold_is_not_met(small_root: Path) -> None:
    golden = small_root / "evals" / "golden" / "documents.yaml"
    golden.write_text(
        golden.read_text(encoding="utf-8").replace("expect: accept", "expect: reject"),
        encoding="utf-8",
    )
    status, out = run(small_root)
    assert status == EXIT_NOT_MET
    assert (
        "| `false_accept_rate` | Documents that must be rejected, accepted | 50.0% (1 of 2)" in out
    )
    assert "- docs/srb-minimal-invoice.xml [srb]: accepted" in out
    assert out.endswith("\nsef-evals: a threshold is not met\n")
    # The report is written all the same: it says what failed.
    report = json.loads((small_root / "evals" / "reports" / "latest.json").read_text("utf-8"))
    assert report["met"] is False


@pytest.mark.parametrize(
    ("path", "text", "problem"),
    [
        ("evals/thresholds.yaml", "agreement: {least: 1}\n", "sef-evals: thresholds.yaml: "),
        ("evals/golden/documents.yaml", "groups: []\n", "sef-evals: documents.yaml: "),
    ],
)
def test_refuses_files_it_cannot_read(small_root: Path, path: str, text: str, problem: str) -> None:
    (small_root / path).write_text(text, encoding="utf-8")
    status, out = run(small_root)
    assert status == EXIT_ERROR
    assert out.startswith(problem)
    assert not (small_root / "evals" / "reports").exists()


def test_says_when_the_rule_sets_are_missing(
    small_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unfetched(root: Path, cases: object) -> list[Measure]:
        raise RulesetNotFoundError("rule set 'en16931' is not present in /nowhere")

    monkeypatch.setattr(verdicts, "measure", unfetched)
    status, out = run(small_root)
    assert (status, out) == (
        EXIT_ERROR,
        "sef-evals: rule set 'en16931' is not present in /nowhere (run `make rulesets`)\n",
    )


def test_runs_as_a_module() -> None:
    done = subprocess.run(
        [sys.executable, "-m", "sef_evals", "--version"],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPOSITORY_ROOT,
    )
    assert (done.returncode, done.stdout) == (0, f"sef-evals {__version__}\n")


@needs_rulesets
def test_the_committed_report_is_what_the_run_gives_and_meets_every_threshold() -> None:
    """The repository's own evaluations, as CI runs them."""
    status, out = run(REPOSITORY_ROOT, "--check")
    assert status == EXIT_MET, out
