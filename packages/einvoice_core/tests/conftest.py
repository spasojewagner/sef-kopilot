"""Shared fixtures: where the test documents live."""

from __future__ import annotations

from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SYNTHETIC_DIR = REPOSITORY_ROOT / "fixtures" / "invoices" / "synthetic"
THIRD_PARTY = REPOSITORY_ROOT / "third_party"

#: Official example documents, fetched by ``scripts/fetch_rulesets.py`` (not committed).
OFFICIAL_EXAMPLE_GLOBS = (
    (THIRD_PARTY / "en16931" / "ubl" / "examples", "*.xml"),
    (THIRD_PARTY / "en16931" / "ubl" / "examples", "*.XML"),
    (THIRD_PARTY / "peppol-bis-billing-3" / "rules" / "examples", "*.xml"),
)


def official_examples() -> list[Path]:
    return sorted(
        path for directory, pattern in OFFICIAL_EXAMPLE_GLOBS for path in directory.glob(pattern)
    )


@pytest.fixture(scope="session")
def synthetic_dir() -> Path:
    return SYNTHETIC_DIR
