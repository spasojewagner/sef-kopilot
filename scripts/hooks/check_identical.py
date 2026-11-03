"""Fail when the given files are not byte-for-byte identical.

Used to keep ``CLAUDE.md`` and ``AGENTS.md`` in sync: two files, one content, because
different coding agents look for different file names.
"""

from __future__ import annotations

import sys
from pathlib import Path

MIN_FILES = 2


def main(paths: list[str]) -> int:
    if len(paths) < MIN_FILES:
        print("usage: check_identical.py FILE FILE [FILE...]", file=sys.stderr)
        return 2

    contents = {path: Path(path).read_bytes() for path in paths}
    reference_path, reference = next(iter(contents.items()))
    different = [path for path, data in contents.items() if data != reference]
    if different:
        names = ", ".join(different)
        print(f"{names} differ from {reference_path}; copy one over the other.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
