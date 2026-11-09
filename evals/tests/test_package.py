"""Smoke tests for the package itself: importable, versioned, typed."""

from importlib.metadata import version
from pathlib import Path

import sef_evals


def test_version_matches_package_metadata() -> None:
    assert sef_evals.__version__ == version("sef-kopilot-evals")


def test_package_ships_type_information() -> None:
    assert (Path(sef_evals.__file__).resolve().parent / "py.typed").is_file()
