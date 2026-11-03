"""Fetch third-party validation rule sets into ``third_party/``.

The UBL 2.1 schemas (OASIS), the EN 16931 validation artefacts (CEN/TC 434) and the Peppol
BIS Billing 3.0 rules are published under their own terms and are *not* part of this
repository: they are fetched on demand from their official sources, verified against a pin,
and copied, unmodified, under ``third_party/<name>/`` together with their license or notice.

Two kinds of source are supported:

* **git** — a tag of an official Git repository, pinned by the commit the tag must resolve to;
* **archive** — a ZIP file at an official HTTPS URL, pinned by its SHA-256 digest.

The manifest (``third_party/manifest.json``) is the single place that says *what* is fetched
and *which version*; this script is only the *how*. Only the standard library and the ``git``
command-line tool are required, so the script runs the same way on a developer machine, in CI
and inside a container.

Usage::

    python scripts/fetch_rulesets.py              # fetch everything that is missing or stale
    python scripts/fetch_rulesets.py --force      # re-fetch everything
    python scripts/fetch_rulesets.py --only en16931
    python scripts/fetch_rulesets.py --check      # verify presence and pins, no network
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import ClassVar

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = REPOSITORY_ROOT / "third_party" / "manifest.json"
DEFAULT_DESTINATION = REPOSITORY_ROOT / "third_party"
SOURCE_RECORD = "SOURCE.json"
NOTICE_FILE = "NOTICE.md"
COMMIT_LENGTH = 40
SHA256_LENGTH = 64
HEX_DIGITS = frozenset("0123456789abcdef")
#: ``file://`` serves tests and offline mirrors; anything fetched over the network is HTTPS.
ARCHIVE_URL_SCHEMES = ("https://", "file://")
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 120
DOWNLOAD_CHUNK_BYTES = 1024 * 1024


class RulesetError(RuntimeError):
    """A rule set could not be fetched or verified."""


def _is_hex(value: str, length: int) -> bool:
    return len(value) == length and set(value) <= HEX_DIGITS


@dataclass(frozen=True)
class GitSource:
    """A tag of a Git repository, pinned by the commit it must resolve to."""

    repository: str
    ref: str
    commit: str

    pin_key: ClassVar[str] = "commit"

    @property
    def pin(self) -> str:
        return self.commit

    def describe(self) -> str:
        return f"{self.repository} at tag {self.ref}"

    def version(self) -> str:
        return f"`{self.ref}` (commit `{self.commit}`)"

    def record(self) -> dict[str, str]:
        return {"repository": self.repository, "ref": self.ref, "commit": self.commit}


@dataclass(frozen=True)
class ArchiveSource:
    """A ZIP archive at a URL, pinned by its SHA-256 digest."""

    url: str
    sha256: str
    strip_prefix: str

    pin_key: ClassVar[str] = "sha256"

    @property
    def pin(self) -> str:
        return self.sha256

    def describe(self) -> str:
        return self.url

    def version(self) -> str:
        return f"archive with SHA-256 `{self.sha256}`"

    def record(self) -> dict[str, str]:
        return {"url": self.url, "sha256": self.sha256, "strip_prefix": self.strip_prefix}


Source = GitSource | ArchiveSource


def _git_source(raw: dict[str, object], name: str) -> GitSource:
    missing = [key for key in ("repository", "ref", "commit") if key not in raw]
    if missing:
        raise RulesetError(f"git source of {name!r} is missing {', '.join(missing)}")
    commit = str(raw["commit"])
    if not _is_hex(commit, COMMIT_LENGTH):
        raise RulesetError(f"'commit' must be a full 40-character SHA-1 in entry {name!r}")
    return GitSource(repository=str(raw["repository"]), ref=str(raw["ref"]), commit=commit)


def _archive_source(raw: dict[str, object], name: str) -> ArchiveSource:
    missing = [key for key in ("url", "sha256") if key not in raw]
    if missing:
        raise RulesetError(f"archive source of {name!r} is missing {', '.join(missing)}")
    url = str(raw["url"])
    if not url.startswith(ARCHIVE_URL_SCHEMES):
        raise RulesetError(f"archive URL of {name!r} must use HTTPS: {url}")
    sha256 = str(raw["sha256"])
    if not _is_hex(sha256, SHA256_LENGTH):
        raise RulesetError(f"'sha256' must be a 64-character lowercase hex digest in {name!r}")
    return ArchiveSource(url=url, sha256=sha256, strip_prefix=str(raw.get("strip_prefix", "")))


@dataclass(frozen=True)
class Ruleset:
    """One entry of the manifest."""

    name: str
    description: str
    source: Source
    license: str
    include: tuple[str, ...]
    notice: str

    @classmethod
    def from_mapping(cls, raw: dict[str, object]) -> Ruleset:
        required = ("name", "description", "license", "include")
        missing = [key for key in required if key not in raw]
        if missing:
            raise RulesetError(f"manifest entry is missing {', '.join(missing)}: {raw!r}")
        name = str(raw["name"])
        include = raw["include"]
        if not isinstance(include, list) or not all(isinstance(item, str) for item in include):
            raise RulesetError(f"'include' must be a list of paths in entry {name!r}")
        is_git, is_archive = "repository" in raw, "url" in raw
        if is_git == is_archive:
            raise RulesetError(
                f"entry {name!r} must define exactly one source: "
                "repository/ref/commit (git) or url/sha256 (archive)"
            )
        source: Source = _git_source(raw, name) if is_git else _archive_source(raw, name)
        return cls(
            name=name,
            description=str(raw["description"]),
            source=source,
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
    """True when the rule set is present and was fetched at the pinned version."""
    record = read_source_record(destination, ruleset)
    return record is not None and record.get(ruleset.source.pin_key) == ruleset.source.pin


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


def _retrieve_git(ruleset: Ruleset, source: GitSource, staging: Path) -> int:
    """Fetch the pinned tag into a temporary checkout and copy the included paths to staging.

    The tag is fetched by its full ref name (``refs/tags/<ref>``) rather than with
    ``git clone --branch``: upstream repositories sometimes carry a branch and a tag with the
    same name, and ``--branch`` would silently prefer the branch.
    """
    print(f"[{ruleset.name}] fetching {source.describe()} ...")
    with tempfile.TemporaryDirectory(prefix="ruleset-") as temp:
        checkout = Path(temp) / "checkout"
        checkout.mkdir()
        _git("init", "--quiet", cwd=checkout)
        _git("remote", "add", "origin", source.repository, cwd=checkout)
        _git("fetch", "--quiet", "--depth", "1", "origin", f"refs/tags/{source.ref}", cwd=checkout)
        _git("-c", "advice.detachedHead=false", "checkout", "--quiet", "FETCH_HEAD", cwd=checkout)
        actual = _git("rev-parse", "HEAD", cwd=checkout)
        if actual != source.commit:
            raise RulesetError(
                f"[{ruleset.name}] tag {source.ref} resolves to commit {actual}, but the "
                f"manifest pins {source.commit}. Either the tag moved upstream or the manifest "
                "is wrong; review the release before changing the pin."
            )
        return _copy_included(checkout, staging, ruleset.include)


def _download(url: str, target: Path) -> str:
    """Stream ``url`` into ``target`` and return its SHA-256 digest (hex)."""
    digest = hashlib.sha256()
    size = 0
    try:
        with (
            urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response,
            target.open("wb") as out,
        ):
            while chunk := response.read(DOWNLOAD_CHUNK_BYTES):
                size += len(chunk)
                if size > MAX_ARCHIVE_BYTES:
                    raise RulesetError(f"{url} is larger than {MAX_ARCHIVE_BYTES} bytes")
                digest.update(chunk)
                out.write(chunk)
    except urllib.error.URLError as error:
        raise RulesetError(f"cannot download {url}: {error.reason}") from error
    except TimeoutError as error:
        raise RulesetError(f"timed out downloading {url}") from error
    return digest.hexdigest()


def _safe_member_path(name: str) -> PurePosixPath:
    """The archive member path, refusing anything that could escape the target directory."""
    path = PurePosixPath(name)
    if "\\" in name or path.is_absolute() or ".." in path.parts:
        raise RulesetError(f"unsafe path in archive: {name!r}")
    return path


def _extract_included(
    archive_path: Path, staging: Path, strip_prefix: str, include: tuple[str, ...]
) -> int:
    """Extract the included paths (files or directories) below ``strip_prefix`` into staging."""
    prefix = PurePosixPath(strip_prefix) if strip_prefix else None
    wanted = [PurePosixPath(item) for item in include]
    matched: set[PurePosixPath] = set()
    extracted = 0
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            member = _safe_member_path(info.filename)
            if prefix is not None:
                if prefix not in member.parents:
                    continue
                member = member.relative_to(prefix)
            hit = next((item for item in wanted if item == member or item in member.parents), None)
            if hit is None:
                continue
            matched.add(hit)
            dest = staging.joinpath(*member.parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as data, dest.open("wb") as out:
                shutil.copyfileobj(data, out)
            extracted += 1
    missing = [str(item) for item in wanted if item not in matched]
    if missing:
        raise RulesetError(f"{', '.join(missing)} not found in the archive; fix the manifest")
    return extracted


def _retrieve_archive(ruleset: Ruleset, source: ArchiveSource, staging: Path) -> int:
    """Download the archive, verify its digest and extract the included paths to staging."""
    print(f"[{ruleset.name}] downloading {source.describe()} ...")
    with tempfile.TemporaryDirectory(prefix="ruleset-") as temp:
        archive_path = Path(temp) / "archive.zip"
        actual = _download(source.url, archive_path)
        if actual != source.sha256:
            raise RulesetError(
                f"[{ruleset.name}] {source.url} has SHA-256 {actual}, but the manifest pins "
                f"{source.sha256}. The archive changed upstream or the download was tampered "
                "with; review it before changing the pin."
            )
        try:
            return _extract_included(archive_path, staging, source.strip_prefix, ruleset.include)
        except zipfile.BadZipFile as error:
            raise RulesetError(f"[{ruleset.name}] {source.url} is not a ZIP archive") from error


def _retrieve(ruleset: Ruleset, staging: Path) -> int:
    if isinstance(ruleset.source, GitSource):
        return _retrieve_git(ruleset, ruleset.source, staging)
    return _retrieve_archive(ruleset, ruleset.source, staging)


def fetch(ruleset: Ruleset, destination: Path) -> Path:
    """Retrieve the pinned rule set and install it under ``destination/<name>``.

    The target directory is replaced atomically from the caller's point of view: the new copy
    is assembled in a staging directory next to it and swapped in only after every check
    passed, so a failed fetch never leaves a half-written rule set behind.
    """
    target = destination / ruleset.name
    staging = destination / f".{ruleset.name}.staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        copied = _retrieve(ruleset, staging)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    record: dict[str, object] = {
        "name": ruleset.name,
        "description": ruleset.description,
        **ruleset.source.record(),
        "license": ruleset.license,
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "files": copied,
    }
    (staging / SOURCE_RECORD).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    (staging / NOTICE_FILE).write_text(render_notice(ruleset), encoding="utf-8")

    if target.exists():
        shutil.rmtree(target)
    staging.rename(target)
    print(f"[{ruleset.name}] {copied} files at {ruleset.source.pin[:12]} -> {target}")
    return target


def render_notice(ruleset: Ruleset) -> str:
    """Provenance and terms, written next to the fetched files."""
    lines = [
        f"# {ruleset.name}",
        "",
        ruleset.description,
        "",
        f"- Source: {ruleset.source.describe()}",
        f"- Version: {ruleset.source.version()}",
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
        key, pinned = ruleset.source.pin_key, ruleset.source.pin
        if record is None:
            problems.append(f"[{ruleset.name}] not fetched (run scripts/fetch_rulesets.py)")
        elif record.get(key) != pinned:
            fetched = record.get(key)
            problems.append(f"[{ruleset.name}] fetched at {key} {fetched}, manifest pins {pinned}")
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
                print(f"[{ruleset.name}] already at {ruleset.source.pin[:12]}, skipping")
                continue
            fetch(ruleset, args.dest)
    except RulesetError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
