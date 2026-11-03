"""Tests for the small helper scripts behind the project-local pre-commit hooks."""

import subprocess
import sys
from pathlib import Path, PurePosixPath

import pytest

import check_identical
import run_in_dir

# Exits 0 when every argument is an existing file relative to the working directory, 3 otherwise.
# Used instead of a shell tool such as `ls` so the test runs identically on Windows and POSIX.
CHECK_FILES_EXIST = (
    "import pathlib, sys; "
    "sys.exit(0 if all(pathlib.Path(p).is_file() for p in sys.argv[1:]) else 3)"
)


@pytest.mark.parametrize(
    ("path", "directory", "expected"),
    [
        ("apps/web/src/app/page.tsx", "apps/web", "src/app/page.tsx"),
        ("apps\\web\\src\\app\\page.tsx", "apps/web", "src/app/page.tsx"),
        ("README.md", "apps/web", "README.md"),
    ],
)
def test_rebase_strips_the_directory_prefix(path: str, directory: str, expected: str) -> None:
    assert run_in_dir.rebase(path, PurePosixPath(directory)) == expected


def test_run_in_dir_executes_the_command_inside_the_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.txt").write_text("a")
    (tmp_path / "pkg" / "b.txt").write_text("b")
    monkeypatch.chdir(tmp_path)

    # Without the wrapper the root-relative names do not resolve from inside `pkg` ...
    direct = subprocess.run(
        [sys.executable, "-c", CHECK_FILES_EXIST, "pkg/a.txt", "pkg/b.txt"],
        cwd=tmp_path / "pkg",
        check=False,
    )
    assert direct.returncode == 3

    # ... and with it they do, because it changes directory and rebases the file arguments.
    code = run_in_dir.main(
        ["pkg", sys.executable, "-c", CHECK_FILES_EXIST, "--", "pkg/a.txt", "pkg/b.txt"]
    )

    assert code == 0


def test_run_in_dir_reports_missing_command() -> None:
    assert run_in_dir.main(["scripts", "definitely-not-a-command-xyz"]) == 127


def test_check_identical_accepts_identical_files(tmp_path: Path) -> None:
    first, second = tmp_path / "CLAUDE.md", tmp_path / "AGENTS.md"
    first.write_bytes(b"same")
    second.write_bytes(b"same")

    assert check_identical.main([str(first), str(second)]) == 0


def test_check_identical_rejects_different_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first, second = tmp_path / "CLAUDE.md", tmp_path / "AGENTS.md"
    first.write_bytes(b"same")
    second.write_bytes(b"different")

    assert check_identical.main([str(first), str(second)]) == 1
    assert "AGENTS.md" in capsys.readouterr().err
