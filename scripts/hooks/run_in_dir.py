"""Run a command inside a sub-directory of the repository, with file paths rebased to it.

pre-commit always passes file names relative to the repository root, but tools such as ESLint
resolve their configuration from the working directory. This wrapper changes into the given
directory, strips its prefix from every file argument and executes the command there.

Usage (from .pre-commit-config.yaml)::

    entry: python scripts/hooks/run_in_dir.py apps/web pnpm exec eslint --max-warnings=0 --
    files: ^apps/web/

Everything after the directory is the command; file names supplied by pre-commit follow it.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath

MIN_ARGUMENTS = 2  # a directory and a command


def rebase(path: str, directory: PurePosixPath) -> str:
    """Return ``path`` relative to ``directory`` (both repository-root relative, POSIX style)."""
    pure = PurePosixPath(path.replace("\\", "/"))
    try:
        return pure.relative_to(directory).as_posix()
    except ValueError:
        return pure.as_posix()


def main(argv: list[str]) -> int:
    if len(argv) < MIN_ARGUMENTS:
        print("usage: run_in_dir.py DIRECTORY COMMAND [ARGS...] [-- FILES...]", file=sys.stderr)
        return 2

    directory = PurePosixPath(argv[0])
    command_and_files = argv[1:]

    # The command ends at the first "--" if present; otherwise everything is the command and
    # pre-commit's file arguments are appended after it.
    if "--" in command_and_files:
        separator = command_and_files.index("--")
        command = command_and_files[:separator]
        files = command_and_files[separator + 1 :]
    else:
        command, files = command_and_files, []

    rebased = [rebase(file, directory) for file in files]
    executable = shutil.which(command[0])
    if executable is None:
        print(f"run_in_dir: command not found: {command[0]}", file=sys.stderr)
        return 127

    result = subprocess.run(
        [executable, *command[1:], *rebased],
        cwd=Path(directory),
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
