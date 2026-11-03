"""Tests for scripts/fetch_rulesets.py against a local throw-away Git repository.

No network is involved: an "upstream" repository is created in a temporary directory, tagged,
and addressed with a ``file://`` URL, which exercises the same clone/verify/copy path as the
real GitHub repositories.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import fetch_rulesets
from fetch_rulesets import Ruleset, RulesetError


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def upstream(tmp_path: Path) -> tuple[str, str]:
    """A tagged repository with rule files and files that must not be copied."""
    repo = tmp_path / "upstream"
    repo.mkdir()
    _git("init", "-q", "-b", "main", cwd=repo)
    _git("config", "user.name", "Fixture", cwd=repo)
    _git("config", "user.email", "fixture@example.invalid", cwd=repo)
    (repo / "rules" / "sch").mkdir(parents=True)
    (repo / "rules" / "sch" / "RULES.sch").write_text("<schema/>")
    (repo / "rules" / "ignored.txt").write_text("not included")
    (repo / "LICENSE.txt").write_text("license text")
    (repo / "build.sh").write_text("#!/bin/sh\n")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "release", cwd=repo)
    _git("tag", "v1.0.0", cwd=repo)
    commit = _git("rev-parse", "HEAD", cwd=repo)
    return repo.as_uri(), commit


def _ruleset(url: str, commit: str, **overrides: object) -> Ruleset:
    fields: dict[str, object] = {
        "name": "demo",
        "description": "Demo rule set",
        "repository": url,
        "ref": "v1.0.0",
        "commit": commit,
        "license": "Example License 1.0",
        "include": ["rules/sch", "LICENSE.txt"],
        "notice": "Provenance notes.",
    }
    fields.update(overrides)
    return Ruleset.from_mapping(fields)


def test_fetch_copies_only_included_paths_and_writes_provenance(
    upstream: tuple[str, str], tmp_path: Path
) -> None:
    url, commit = upstream
    destination = tmp_path / "third_party"

    target = fetch_rulesets.fetch(_ruleset(url, commit), destination)

    assert (target / "rules" / "sch" / "RULES.sch").read_text() == "<schema/>"
    assert (target / "LICENSE.txt").is_file()
    assert not (target / "rules" / "ignored.txt").exists()
    assert not (target / "build.sh").exists()

    record = json.loads((target / "SOURCE.json").read_text())
    assert record["commit"] == commit
    assert record["ref"] == "v1.0.0"
    assert record["files"] == 2
    notice = (target / "NOTICE.md").read_text()
    assert "Example License 1.0" in notice
    assert "Provenance notes." in notice
    assert fetch_rulesets.is_current(destination, _ruleset(url, commit))


def test_fetch_refuses_a_tag_that_does_not_match_the_pinned_commit(
    upstream: tuple[str, str], tmp_path: Path
) -> None:
    url, _ = upstream
    wrong_commit = "0" * 40

    with pytest.raises(RulesetError, match=r"tag v1\.0\.0 resolves to commit"):
        fetch_rulesets.fetch(_ruleset(url, wrong_commit), tmp_path / "third_party")

    assert not (tmp_path / "third_party" / "demo").exists()


def test_fetch_fails_when_an_included_path_is_missing(
    upstream: tuple[str, str], tmp_path: Path
) -> None:
    url, commit = upstream

    with pytest.raises(RulesetError, match="does not exist in the checkout"):
        fetch_rulesets.fetch(
            _ruleset(url, commit, include=["rules/sch", "missing.txt"]), tmp_path / "third_party"
        )

    # Nothing half-written is left behind: neither the target nor the staging directory.
    assert not (tmp_path / "third_party" / "demo").exists()
    assert not (tmp_path / "third_party" / ".demo.staging").exists()


def test_check_reports_missing_and_stale_rule_sets(
    upstream: tuple[str, str], tmp_path: Path
) -> None:
    url, commit = upstream
    destination = tmp_path / "third_party"
    ruleset = _ruleset(url, commit)

    assert fetch_rulesets.check([ruleset], destination) == [
        "[demo] not fetched (run scripts/fetch_rulesets.py)"
    ]

    fetch_rulesets.fetch(ruleset, destination)
    assert fetch_rulesets.check([ruleset], destination) == []

    stale = _ruleset(url, "f" * 40)
    (problem,) = fetch_rulesets.check([stale], destination)
    assert problem.startswith("[demo] fetched at")


def test_main_skips_current_rule_sets_and_honours_only(
    upstream: tuple[str, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    url, commit = upstream
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "rulesets": [
                    {
                        "name": "demo",
                        "description": "Demo rule set",
                        "repository": url,
                        "ref": "v1.0.0",
                        "commit": commit,
                        "license": "Example License 1.0",
                        "include": ["LICENSE.txt"],
                    },
                    {
                        "name": "other",
                        "description": "Never fetched in this test",
                        "repository": url,
                        "ref": "v1.0.0",
                        "commit": commit,
                        "license": "Example License 1.0",
                        "include": ["LICENSE.txt"],
                    },
                ]
            }
        )
    )
    destination = tmp_path / "third_party"
    base = ["--manifest", str(manifest), "--dest", str(destination)]

    assert fetch_rulesets.main([*base, "--only", "demo"]) == 0
    assert (destination / "demo" / "LICENSE.txt").is_file()
    assert not (destination / "other").exists()

    assert fetch_rulesets.main([*base, "--only", "demo"]) == 0
    assert "already at" in capsys.readouterr().out

    assert fetch_rulesets.main([*base, "--check", "--only", "demo"]) == 0
    assert fetch_rulesets.main([*base, "--check"]) == 1
    assert fetch_rulesets.main([*base, "--only", "nope"]) == 1


@pytest.mark.parametrize(
    ("broken", "message"),
    [
        ({"commit": "abc"}, "full 40-character"),
        ({"include": "rules"}, "'include' must be a list"),
    ],
)
def test_manifest_entries_are_validated(broken: dict[str, object], message: str) -> None:
    entry: dict[str, object] = {
        "name": "demo",
        "description": "Demo",
        "repository": "https://example.invalid/repo",
        "ref": "v1",
        "commit": "a" * 40,
        "license": "L",
        "include": ["x"],
    }
    entry.update(broken)

    with pytest.raises(RulesetError, match=message):
        Ruleset.from_mapping(entry)


def test_manifest_requires_every_field(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"rulesets": [{"name": "demo"}]}))

    with pytest.raises(RulesetError, match="missing description"):
        fetch_rulesets.load_manifest(manifest)


def test_project_manifest_is_valid() -> None:
    """The real manifest must always load; this is the cheapest guard against typos."""
    rulesets = fetch_rulesets.load_manifest(fetch_rulesets.DEFAULT_MANIFEST)

    assert [ruleset.name for ruleset in rulesets] == ["en16931", "peppol-bis-billing-3"]
    assert all(ruleset.repository.startswith("https://github.com/") for ruleset in rulesets)
