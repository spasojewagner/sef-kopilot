"""Fetch third-party validation rule sets into ``third_party/``.

The EN 16931 validation artefacts (CEN/TC 434) and the Peppol BIS Billing 3.0 rules are
published under their own terms and are *not* part of this repository: they are fetched on
demand from their official Git repositories at a pinned tag, verified against a pinned commit
and copied, unmodified, under ``third_party/<name>/`` together with their license or notice.

The manifest (``third_party/manifest.json``) is the single place that says *what* is fetched
and *which version*; this script is only the *how*. Only the standard library and the ``git``
command-line tool are required, so the script runs the same way on a developer machine, in CI
and inside a container.

Usage::

    python scripts/fetch_rulesets.py              # fetch everything that is missing or stale
    python scripts/fetch_rulesets.py --force      # re-fetch everything
    python scripts/fetch_rulesets.py --only en16931
    python scripts/fetch_rulesets.py --check      # verify presence and pinned commits, no network
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = REPOSITORY_ROOT / "third_party" / "manifest.json"
DEFAULT_DESTINATION = REPOSITORY_ROOT / "third_party"
SOURCE_RECORD = "SOURCE.json"
NOTICE_FILE = "NOTICE.md"
COMMIT_LENGTH = 40


class RulesetError(RuntimeError):
    """A rule set could not be fetched or verified."""


@dataclass(frozen=True)
class Ruleset:
    """One entry of the manifest."""

    name: str
    description: str
    repository: str
    ref: str
    commit: str
    license: str
    include: tuple[str, ...]
    notice: str

    @classmethod
    def from_mapping(cls, raw: dict[str, object]) -> Ruleset:
        required = ("name", "description", "repository", "ref", "commit", "license", "include")
        missing = [key for key in required if key not in raw]
        if missing:
            raise RulesetError(f"manifest entry is missing {', '.join(missing)}: {raw!r}")
        include = raw["include"]
        if not isinstance(include, list) or not all(isinstance(item, str) for item in include):
            raise RulesetError(f"'include' must be a list of paths in entry {raw.get('name')!r}")
        commit = str(raw["commit"])
        if len(commit) != COMMIT_LENGTH or any(c not in "0123456789abcdef" for c in commit):
            raise RulesetError(
                f"'commit' must be a full 40-character SHA-1 in entry {raw['name']!r}"
            )
        return cls(
            name=str(raw["name"]),
            description=str(raw["description"]),
            repository=str(raw["repository"]),
            ref=str(raw["ref"]),
            commit=commit,
            license=str(raw["license"]),
            include=tuple(include),
            notice=str(raw.get("notice", "")),
        )


def load_manifest(path: Path) -> list[Ruleset]:
    """Read and validate the manifest; the order of entries is preserved."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RulesetError(f"cannot read manifest {path}: {error}") from error
    entries = data.get("rulesets") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries:
        raise RulesetError(f"manifest {path} must contain a non-empty 'rulesets' list")
    rulesets = [Ruleset.from_mapping(entry) for entry in entries]
    names = [ruleset.name for ruleset in rulesets]
    if len(set(names)) != len(names):
        raise RulesetError(f"manifest {path} has duplicate rule set names")
    return rulesets


def _git(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RulesetError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def read_source_record(destination: Path, ruleset: Ruleset) -> dict[str, object] | None:
    """Return the provenance record of an already fetched rule set, or ``None``."""
    record_path = destination / ruleset.name / SOURCE_RECORD
    if not record_path.is_file():
        return None
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return record if isinstance(record, dict) else None


def is_current(destination: Path, ruleset: Ruleset) -> bool:
    """True when the rule set is present and was fetched at the pinned commit."""
    record = read_source_record(destination, ruleset)
    return record is not None and record.get("commit") == ruleset.commit


def _copy_included(checkout: Path, target: Path, include: tuple[str, ...]) -> int:
    copied = 0
    for item in include:
        relative = PurePosixPath(item)
        source = checkout / relative
        if not source.exists():
            raise RulesetError(f"'{item}' does not exist in the checkout; fix the manifest")
        dest = target / relative
        if source.is_dir():
            shutil.copytree(source, dest, dirs_exist_ok=True)
            copied += sum(1 for path in dest.rglob("*") if path.is_file())
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
            copied += 1
    return copied


def fetch(ruleset: Ruleset, destination: Path) -> Path:
    """Fetch the pinned tag, verify the commit and copy the included paths.

    The tag is fetched by its full ref name (``refs/tags/<ref>``) rather than with
    ``git clone --branch``: upstream repositories sometimes carry a branch and a tag with the
    same name, and ``--branch`` would silently prefer the branch.

    The target directory is replaced atomically from the caller's point of view: the new copy
    is assembled next to it and swapped in only after every check passed.
    """
    target = destination / ruleset.name
    staging = destination / f".{ruleset.name}.staging"
    print(f"[{ruleset.name}] fetching {ruleset.repository} at tag {ruleset.ref} ...")
    with tempfile.TemporaryDirectory(prefix="ruleset-") as temp:
        checkout = Path(temp) / "checkout"
        checkout.mkdir()
        _git("init", "--quiet", cwd=checkout)
        _git("remote", "add", "origin", ruleset.repository, cwd=checkout)
        _git("fetch", "--quiet", "--depth", "1", "origin", f"refs/tags/{ruleset.ref}", cwd=checkout)
        _git("-c", "advice.detachedHead=false", "checkout", "--quiet", "FETCH_HEAD", cwd=checkout)
        actual = _git("rev-parse", "HEAD", cwd=checkout)
        if actual != ruleset.commit:
            raise RulesetError(
                f"[{ruleset.name}] tag {ruleset.ref} resolves to commit {actual}, but the "
                f"manifest pins {ruleset.commit}. Either the tag moved upstream or the manifest "
                "is wrong; review the release before changing the pin."
            )
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        copied = _copy_included(checkout, staging, ruleset.include)

    record = {
        "name": ruleset.name,
        "description": ruleset.description,
        "repository": ruleset.repository,
        "ref": ruleset.ref,
        "commit": ruleset.commit,
        "license": ruleset.license,
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "files": copied,
    }
    (staging / SOURCE_RECORD).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    (staging / NOTICE_FILE).write_text(render_notice(ruleset), encoding="utf-8")

    if target.exists():
        shutil.rmtree(target)
    staging.rename(target)
    print(f"[{ruleset.name}] {copied} files at {ruleset.commit[:12]} -> {target}")
    return target


def render_notice(ruleset: Ruleset) -> str:
    """Provenance and terms, written next to the fetched files."""
    lines = [
        f"# {ruleset.name}",
        "",
        ruleset.description,
        "",
        f"- Source: {ruleset.repository}",
        f"- Version: `{ruleset.ref}` (commit `{ruleset.commit}`)",
        f"- License / terms: {ruleset.license}",
        "",
        "These files were fetched by `scripts/fetch_rulesets.py`, are not modified by this",
        "project and are not part of its repository or distribution.",
    ]
    if ruleset.notice:
        lines += ["", ruleset.notice]
    return "\n".join(lines) + "\n"


def check(rulesets: list[Ruleset], destination: Path) -> list[str]:
    """Return a problem description per rule set that is missing or stale (empty = all good)."""
    problems = []
    for ruleset in rulesets:
        record = read_source_record(destination, ruleset)
        if record is None:
            problems.append(f"[{ruleset.name}] not fetched (run scripts/fetch_rulesets.py)")
        elif record.get("commit") != ruleset.commit:
            fetched = record.get("commit")
            pinned = ruleset.commit
            problems.append(f"[{ruleset.name}] fetched at {fetched}, manifest pins {pinned}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--dest", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--only", action="append", metavar="NAME", help="fetch only this rule set")
    parser.add_argument("--force", action="store_true", help="re-fetch even if already current")
    parser.add_argument(
        "--check", action="store_true", help="verify only; never touches the network"
    )
    args = parser.parse_args(argv)

    try:
        rulesets = load_manifest(args.manifest)
        if args.only:
            unknown = set(args.only) - {ruleset.name for ruleset in rulesets}
            if unknown:
                raise RulesetError(f"unknown rule set(s): {', '.join(sorted(unknown))}")
            rulesets = [ruleset for ruleset in rulesets if ruleset.name in set(args.only)]

        if args.check:
            problems = check(rulesets, args.dest)
            for problem in problems:
                print(problem, file=sys.stderr)
            return 1 if problems else 0

        args.dest.mkdir(parents=True, exist_ok=True)
        for ruleset in rulesets:
            if not args.force and is_current(args.dest, ruleset):
                print(f"[{ruleset.name}] already at {ruleset.commit[:12]}, skipping")
                continue
            fetch(ruleset, args.dest)
    except RulesetError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
