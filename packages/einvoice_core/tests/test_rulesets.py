"""Locating the fetched rule sets."""

from pathlib import Path

import pytest

from einvoice_core import rulesets
from einvoice_core.rulesets import ENV_VAR, RulesetNotFoundError, ruleset_path, rulesets_dir

from .conftest import REPOSITORY_ROOT


def _fetched(root: Path, name: str) -> Path:
    path = root / name
    path.mkdir(parents=True)
    (path / "SOURCE.json").write_text("{}")
    return path


def test_defaults_to_the_repository_third_party_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)

    assert rulesets_dir() == REPOSITORY_ROOT / "third_party"


def test_environment_variable_overrides_the_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ENV_VAR, str(tmp_path))
    expected = _fetched(tmp_path, "ubl-2.1")

    assert rulesets_dir() == tmp_path
    assert ruleset_path("ubl-2.1") == expected


def test_environment_variable_must_name_a_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "missing"))

    with pytest.raises(RulesetNotFoundError, match="is not a directory"):
        rulesets_dir()


def test_a_rule_set_without_provenance_record_is_not_present(tmp_path: Path) -> None:
    (tmp_path / "ubl-2.1").mkdir()  # e.g. an interrupted manual copy

    with pytest.raises(RulesetNotFoundError, match="run `make rulesets`"):
        ruleset_path("ubl-2.1", root=tmp_path)


def test_outside_a_repository_the_error_explains_what_to_do(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.setattr(rulesets, "__file__", str(tmp_path / "site-packages" / "rulesets.py"))

    with pytest.raises(RulesetNotFoundError, match=ENV_VAR):
        rulesets_dir()
