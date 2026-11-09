"""Shared fixtures: the repository the evaluations measure, and a small one to run them in."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from einvoice_core.rulesets import RulesetNotFoundError, ruleset_path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SYNTHETIC_DIR = REPOSITORY_ROOT / "fixtures" / "invoices" / "synthetic"
MUTATIONS_DIR = SYNTHETIC_DIR / "mutations"


def _fetched() -> bool:
    try:
        for name in ("ubl-2.1", "en16931", "peppol-bis-billing-3"):
            ruleset_path(name)
    except RulesetNotFoundError:
        return False
    return True


#: For tests that validate documents: the rule sets must have been fetched (``make rulesets``).
needs_rulesets = pytest.mark.skipif(
    not _fetched(), reason="rule sets not fetched (run `make rulesets`)"
)

THRESHOLDS = """\
agreement: {min: 1.0}
false_accept_rate: {max: 0.0}
detection: {min: 1.0}
"""

DOCUMENTS = """\
groups:
  - name: valid
    title: A valid Serbian invoice
    documents: docs/srb-minimal-invoice.xml
    profile: srb
    expect: accept
  - name: mistaken
    title: An invoice with a wrong check digit in its PIB
    documents: docs/srb-009-pib-check-digit.xml
    profile: srb
    expect: reject
    reports: header
"""


@pytest.fixture
def small_root(tmp_path: Path) -> Path:
    """A repository with two documents, a golden set of them and thresholds, in which the
    runner can be run and its report written."""
    (tmp_path / "docs").mkdir()
    shutil.copy(SYNTHETIC_DIR / "srb-minimal-invoice.xml", tmp_path / "docs")
    shutil.copy(MUTATIONS_DIR / "srb-009-pib-check-digit.xml", tmp_path / "docs")
    (tmp_path / "third_party").mkdir()
    shutil.copy(REPOSITORY_ROOT / "third_party" / "manifest.json", tmp_path / "third_party")
    (tmp_path / "evals" / "golden").mkdir(parents=True)
    (tmp_path / "evals" / "thresholds.yaml").write_text(THRESHOLDS, encoding="utf-8")
    (tmp_path / "evals" / "golden" / "documents.yaml").write_text(DOCUMENTS, encoding="utf-8")
    return tmp_path
