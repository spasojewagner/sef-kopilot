"""Smoke tests for the package itself: importable, versioned, typed."""

from importlib.metadata import version
from pathlib import Path

import einvoice_core


def test_version_matches_package_metadata() -> None:
    """``__version__`` must equal the version declared in ``pyproject.toml``.

    The two are maintained by hand; this test is what keeps them from drifting apart.
    """
    assert einvoice_core.__version__ == version("einvoice-core")


def test_package_ships_type_information() -> None:
    """The ``py.typed`` marker (PEP 561) must be part of the installed package."""
    package_dir = Path(einvoice_core.__file__).resolve().parent
    assert (package_dir / "py.typed").is_file()
