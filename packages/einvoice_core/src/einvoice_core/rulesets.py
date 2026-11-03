"""Where the fetched third-party rule sets live.

The UBL schemas and the Schematron rule sets are published under their own terms and are
fetched into ``third_party/`` by ``scripts/fetch_rulesets.py`` instead of being shipped with
the code (see ``third_party/README.md``). This module finds them:

1. the directory named by the ``EINVOICE_RULESETS_DIR`` environment variable, when set
   (containers and deployments copy the fetched rule sets wherever they like);
2. otherwise the ``third_party/`` directory of the repository this package is installed from
   (development and CI, where the workspace installs the package in editable mode).

A rule set counts as present only when its ``SOURCE.json`` provenance record exists, which the
fetcher writes last; a half-copied directory is therefore never mistaken for a rule set.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

__all__ = ["ENV_VAR", "RulesetNotFoundError", "ruleset_path", "rulesets_dir"]

ENV_VAR: Final = "EINVOICE_RULESETS_DIR"
_MANIFEST: Final = Path("third_party") / "manifest.json"
_SOURCE_RECORD: Final = "SOURCE.json"
_HINT: Final = f"run `make rulesets` (python scripts/fetch_rulesets.py) or set {ENV_VAR}"


class RulesetNotFoundError(FileNotFoundError):
    """A rule set the validator needs has not been fetched."""


def _repository_third_party(start: Path) -> Path | None:
    for directory in (start, *start.parents):
        if (directory / _MANIFEST).is_file():
            return directory / _MANIFEST.parent
    return None


def rulesets_dir() -> Path:
    """The directory holding the fetched rule sets (see the module documentation)."""
    configured = os.environ.get(ENV_VAR)
    if configured:
        path = Path(configured)
        if not path.is_dir():
            raise RulesetNotFoundError(f"{ENV_VAR} points to {path}, which is not a directory")
        return path
    found = _repository_third_party(Path(__file__).resolve().parent)
    if found is None:
        raise RulesetNotFoundError(f"no rule set directory found: {_HINT}")
    return found


def ruleset_path(name: str, *, root: Path | None = None) -> Path:
    """The directory of the fetched rule set ``name``, e.g. ``ruleset_path("ubl-2.1")``."""
    base = root if root is not None else rulesets_dir()
    path = base / name
    if not (path / _SOURCE_RECORD).is_file():
        raise RulesetNotFoundError(f"rule set {name!r} is not present in {base}: {_HINT}")
    return path
