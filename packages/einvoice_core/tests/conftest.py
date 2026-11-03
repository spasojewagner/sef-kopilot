"""Shared fixtures: where the test documents live."""

from __future__ import annotations

from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SYNTHETIC_DIR = REPOSITORY_ROOT / "fixtures" / "invoices" / "synthetic"
THIRD_PARTY = REPOSITORY_ROOT / "third_party"

#: Official example documents, fetched by ``scripts/fetch_rulesets.py`` (not committed).
OFFICIAL_EXAMPLE_DIRS = (
    THIRD_PARTY / "en16931" / "ubl" / "examples",
    THIRD_PARTY / "peppol-bis-billing-3" / "rules" / "examples",
)


def official_examples() -> list[Path]:
    """Every XML file in the example directories, listed once whatever the extension's case.

    CEN ships two examples as ``.XML``. Globbing ``*.xml`` and ``*.XML`` separately would list
    every example twice on a case-insensitive file system (Windows, macOS by default).
    """
    return sorted(
        path
        for directory in OFFICIAL_EXAMPLE_DIRS
        if directory.is_dir()
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() == ".xml"
    )


@pytest.fixture(scope="session")
def synthetic_dir() -> Path:
    return SYNTHETIC_DIR
