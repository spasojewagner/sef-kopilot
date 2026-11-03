"""Tests for scripts/fetch_rulesets.py against a local throw-away Git repository.

No network is involved: an "upstream" repository is created in a temporary directory, tagged,
and addressed with a ``file://`` URL, which exercises the same clone/verify/copy path as the
real GitHub repositories.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

import pytest

import fetch_rulesets
from fetch_rulesets import ArchiveSource, GitSource, Ruleset, RulesetError


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
        ({"url": "https://example.invalid/a.zip"}, "exactly one source"),
        ({"ref": None, "repository": None}, None),
    ],
)
def test_manifest_entries_are_validated(broken: dict[str, object], message: str | None) -> None:
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
    entry = {key: value for key, value in entry.items() if value is not None}

    if message is None:  # removing the git keys leaves no source at all
        message = "exactly one source"
    with pytest.raises(RulesetError, match=message):
        Ruleset.from_mapping(entry)


def test_manifest_requires_every_field(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"rulesets": [{"name": "demo"}]}))

    with pytest.raises(RulesetError, match="missing description, license, include"):
        fetch_rulesets.load_manifest(manifest)


def test_project_manifest_is_valid() -> None:
    """The real manifest must always load; this is the cheapest guard against typos."""
    rulesets = fetch_rulesets.load_manifest(fetch_rulesets.DEFAULT_MANIFEST)

    assert [ruleset.name for ruleset in rulesets] == ["ubl-2.1", "en16931", "peppol-bis-billing-3"]
    ubl, *git_rulesets = rulesets
    assert isinstance(ubl.source, ArchiveSource)
    assert ubl.source.url.startswith("https://docs.oasis-open.org/")
    for ruleset in git_rulesets:
        assert isinstance(ruleset.source, GitSource)
        assert ruleset.source.repository.startswith("https://github.com/")


def test_git_source_requires_its_three_fields() -> None:
    with pytest.raises(RulesetError, match="git source of 'demo' is missing ref, commit"):
        Ruleset.from_mapping(
            {
                "name": "demo",
                "description": "D",
                "license": "L",
                "include": ["x"],
                "repository": "r",
            }
        )


# --- archive sources ----------------------------------------------------------------------


def _zip(path: Path, members: dict[str, bytes]) -> tuple[str, str]:
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return path.as_uri(), hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def archive(tmp_path: Path) -> tuple[str, str]:
    """A release archive with a top-level folder, schemas in two folders and noise."""
    return _zip(
        tmp_path / "pkg-1.0.zip",
        {
            "pkg-1.0/xsd/maindoc/Doc.xsd": b"<schema/>",
            "pkg-1.0/xsd/common/Types.xsd": b"<types/>",
            "pkg-1.0/xsd/common/More.xsd": b"<more/>",
            "pkg-1.0/doc/manual.html": b"<html/>",
            "pkg-1.0/README.txt": b"readme",
            "elsewhere/xsd/maindoc/Doc.xsd": b"outside the prefix",
        },
    )


def _archive_ruleset(url: str, sha256: str, **overrides: object) -> Ruleset:
    fields: dict[str, object] = {
        "name": "schemas",
        "description": "Demo schemas",
        "url": url,
        "sha256": sha256,
        "strip_prefix": "pkg-1.0",
        "license": "Example Terms",
        "include": ["xsd/maindoc/Doc.xsd", "xsd/common"],
    }
    fields.update(overrides)
    return Ruleset.from_mapping(fields)


def test_archive_fetch_extracts_included_paths_below_the_prefix(
    archive: tuple[str, str], tmp_path: Path
) -> None:
    url, sha256 = archive
    destination = tmp_path / "third_party"
    ruleset = _archive_ruleset(url, sha256)

    target = fetch_rulesets.fetch(ruleset, destination)

    assert (target / "xsd" / "maindoc" / "Doc.xsd").read_bytes() == b"<schema/>"
    assert (target / "xsd" / "common" / "Types.xsd").is_file()
    assert (target / "xsd" / "common" / "More.xsd").is_file()
    assert not (target / "doc").exists()
    assert not (target / "README.txt").exists()

    record = json.loads((target / "SOURCE.json").read_text())
    assert record["url"] == url
    assert record["sha256"] == sha256
    assert record["files"] == 3
    assert "commit" not in record
    assert f"SHA-256 `{sha256}`" in (target / "NOTICE.md").read_text()
    assert fetch_rulesets.is_current(destination, ruleset)
    assert fetch_rulesets.check([ruleset], destination) == []


def test_archive_without_prefix_uses_member_paths_as_they_are(tmp_path: Path) -> None:
    url, sha256 = _zip(tmp_path / "flat.zip", {"xsd/a.xsd": b"a", "other.txt": b"o"})

    target = fetch_rulesets.fetch(
        _archive_ruleset(url, sha256, strip_prefix="", include=["xsd"]), tmp_path / "out"
    )

    assert (target / "xsd" / "a.xsd").read_bytes() == b"a"
    assert not (target / "other.txt").exists()


def test_archive_with_a_different_digest_is_refused(
    archive: tuple[str, str], tmp_path: Path
) -> None:
    url, _ = archive
    destination = tmp_path / "third_party"

    with pytest.raises(RulesetError, match="but the manifest pins"):
        fetch_rulesets.fetch(_archive_ruleset(url, "0" * 64), destination)

    assert not (destination / "schemas").exists()
    assert not (destination / ".schemas.staging").exists()


def test_archive_include_that_matches_nothing_is_an_error(
    archive: tuple[str, str], tmp_path: Path
) -> None:
    url, sha256 = archive

    with pytest.raises(RulesetError, match="xsd/missing not found in the archive"):
        fetch_rulesets.fetch(
            _archive_ruleset(url, sha256, include=["xsd/common", "xsd/missing"]), tmp_path / "out"
        )


@pytest.mark.parametrize("member", ["pkg-1.0/../../evil.txt", "/etc/evil.txt", "pkg-1.0\\evil.txt"])
def test_archive_members_that_could_escape_are_refused(member: str, tmp_path: Path) -> None:
    url, sha256 = _zip(tmp_path / "evil.zip", {member: b"x", "pkg-1.0/xsd/common/a.xsd": b"a"})

    with pytest.raises(RulesetError, match="unsafe path in archive"):
        fetch_rulesets.fetch(_archive_ruleset(url, sha256, include=["xsd"]), tmp_path / "out")


def test_archive_that_is_not_a_zip_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "not.zip"
    path.write_bytes(b"this is not a zip archive")
    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()

    with pytest.raises(RulesetError, match="is not a ZIP archive"):
        fetch_rulesets.fetch(_archive_ruleset(path.as_uri(), sha256), tmp_path / "out")


def test_archive_download_failure_is_reported(tmp_path: Path) -> None:
    missing = (tmp_path / "missing.zip").as_uri()

    with pytest.raises(RulesetError, match="cannot download"):
        fetch_rulesets.fetch(_archive_ruleset(missing, "a" * 64), tmp_path / "out")


def test_archive_download_size_is_limited(
    archive: tuple[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url, sha256 = archive
    monkeypatch.setattr(fetch_rulesets, "MAX_ARCHIVE_BYTES", 16)

    with pytest.raises(RulesetError, match="is larger than 16 bytes"):
        fetch_rulesets.fetch(_archive_ruleset(url, sha256), tmp_path / "out")


@pytest.mark.parametrize(
    ("broken", "message"),
    [
        ({"url": "http://example.invalid/a.zip"}, "must use HTTPS"),
        ({"sha256": "ABC"}, "64-character lowercase hex"),
        ({"sha256": None}, "archive source of 'schemas' is missing sha256"),
    ],
)
def test_archive_entries_are_validated(broken: dict[str, object], message: str) -> None:
    entry: dict[str, object] = {
        "name": "schemas",
        "description": "Demo schemas",
        "url": "https://example.invalid/a.zip",
        "sha256": "a" * 64,
        "license": "L",
        "include": ["xsd"],
    }
    entry.update(broken)
    entry = {key: value for key, value in entry.items() if value is not None}

    with pytest.raises(RulesetError, match=message):
        Ruleset.from_mapping(entry)


def test_archive_source_defaults_to_no_prefix() -> None:
    ruleset = Ruleset.from_mapping(
        {
            "name": "schemas",
            "description": "D",
            "url": "https://example.invalid/a.zip",
            "sha256": "b" * 64,
            "license": "L",
            "include": ["xsd"],
        }
    )

    assert ruleset.source == ArchiveSource(
        url="https://example.invalid/a.zip", sha256="b" * 64, strip_prefix=""
    )


def test_check_reports_a_stale_archive(archive: tuple[str, str], tmp_path: Path) -> None:
    url, sha256 = archive
    destination = tmp_path / "third_party"
    fetch_rulesets.fetch(_archive_ruleset(url, sha256), destination)

    (problem,) = fetch_rulesets.check([_archive_ruleset(url, "c" * 64)], destination)

    assert problem == f"[schemas] fetched at sha256 {sha256}, manifest pins {'c' * 64}"


# --- manifest and record edge cases -------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("{not json", "cannot read manifest"),
        (json.dumps({"rulesets": []}), "non-empty 'rulesets' list"),
        (json.dumps([]), "non-empty 'rulesets' list"),
    ],
)
def test_unreadable_or_empty_manifests_are_rejected(
    content: str, message: str, tmp_path: Path
) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(content)

    with pytest.raises(RulesetError, match=message):
        fetch_rulesets.load_manifest(manifest)


def test_duplicate_rule_set_names_are_rejected(tmp_path: Path) -> None:
    entry = {
        "name": "demo",
        "description": "D",
        "url": "https://example.invalid/a.zip",
        "sha256": "a" * 64,
        "license": "L",
        "include": ["x"],
    }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"rulesets": [entry, entry]}))

    with pytest.raises(RulesetError, match="duplicate rule set names"):
        fetch_rulesets.load_manifest(manifest)


def test_a_corrupt_source_record_counts_as_not_fetched(tmp_path: Path) -> None:
    ruleset = _archive_ruleset("https://example.invalid/a.zip", "a" * 64)
    (tmp_path / "schemas").mkdir()
    (tmp_path / "schemas" / "SOURCE.json").write_text("{broken")

    assert not fetch_rulesets.is_current(tmp_path, ruleset)
    assert fetch_rulesets.check([ruleset], tmp_path) == [
        "[schemas] not fetched (run scripts/fetch_rulesets.py)"
    ]


def test_git_failures_are_reported(tmp_path: Path) -> None:
    missing_repository = (tmp_path / "no-such-repo").as_uri()

    with pytest.raises(RulesetError, match=r"git fetch .* failed"):
        fetch_rulesets.fetch(_ruleset(missing_repository, "a" * 40), tmp_path / "out")
