"""Shared fixtures: the repository the evaluations measure."""

from __future__ import annotations

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
