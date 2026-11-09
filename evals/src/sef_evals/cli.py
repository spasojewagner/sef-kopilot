"""``sef-evals``: run the evaluations, write their report, or check it (ADR-0054).

    sef-evals            # measure, print the table, write evals/reports/latest.{json,md}
    sef-evals --check    # measure, and fail if a threshold is not met or the report is stale

Run from the repository or below it: the root is the nearest directory up that holds
``evals/thresholds.yaml``. The validator needs the fetched rule sets (``make rulesets``).

Exit status: 0 when every threshold is met (and, with ``--check``, the committed report is what
the run gives); 1 when one is not, or the report is stale; 2 for a golden set or a thresholds'
file that cannot be read, or rule sets that have not been fetched.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final, TextIO

from einvoice_core.rulesets import RulesetNotFoundError
from sef_evals import __version__, verdicts
from sef_evals.golden import GoldenError, load_cases
from sef_evals.report import JSON_NAME, MARKDOWN_NAME, as_json, as_markdown, versions
from sef_evals.thresholds import ThresholdError, judge, load_thresholds

__all__ = ["EXIT_ERROR", "EXIT_MET", "EXIT_NOT_MET", "main"]

EXIT_MET: Final = 0
EXIT_NOT_MET: Final = 1
EXIT_ERROR: Final = 2

THRESHOLDS: Final = Path("evals/thresholds.yaml")
DOCUMENTS: Final = Path("evals/golden/documents.yaml")
REPORTS: Final = Path("evals/reports")


def find_root(start: Path) -> Path | None:
    """The nearest directory from ``start`` up that holds ``evals/thresholds.yaml``."""
    for directory in (start, *start.parents):
        if (directory / THRESHOLDS).is_file():
            return directory
    return None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sef-evals",
        description="Measure SEF Kopilot on its golden sets and judge the measures against "
        "evals/thresholds.yaml.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="write nothing; fail if a threshold is not met or evals/reports is stale",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _stale(root: Path, written: dict[str, str]) -> list[str]:
    """The report's files that are not what the run gives."""
    return [
        (REPORTS / name).as_posix()
        for name, text in written.items()
        if not (root / REPORTS / name).is_file()
        or (root / REPORTS / name).read_text(encoding="utf-8") != text
    ]


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    out: TextIO | None = None,
) -> int:
    """Run the command line; returns the exit status."""
    args = _parser().parse_args(argv)
    out = out or sys.stdout
    root = find_root((cwd or Path.cwd()).resolve())
    if root is None:
        print(f"sef-evals: no {THRESHOLDS.as_posix()} here or above", file=out)
        return EXIT_ERROR
    try:
        thresholds = load_thresholds(root / THRESHOLDS)
        cases = load_cases(root, root / DOCUMENTS)
        measures = verdicts.measure(root, cases)
    except (GoldenError, ThresholdError) as error:
        print(f"sef-evals: {error}", file=out)
        return EXIT_ERROR
    except RulesetNotFoundError as error:
        print(f"sef-evals: {error} (run `make rulesets`)", file=out)
        return EXIT_ERROR
    judgements = judge(measures, thresholds)
    measured = versions(root)
    written = {
        JSON_NAME: as_json(judgements, measured),
        MARKDOWN_NAME: as_markdown(judgements, measured),
    }
    out.write(written[MARKDOWN_NAME])
    met = all(judgement.met is not False for judgement in judgements)
    stale = _stale(root, written) if args.check else []
    if stale:
        print(f"\nsef-evals: the report is stale, run `make evals`: {', '.join(stale)}", file=out)
    if not args.check:
        (root / REPORTS).mkdir(parents=True, exist_ok=True)
        for name, text in written.items():
            (root / REPORTS / name).write_text(text, encoding="utf-8", newline="\n")
    if not met:
        print("\nsef-evals: a threshold is not met", file=out)
    return EXIT_MET if met and not stale else EXIT_NOT_MET


def console() -> None:
    """The ``sef-evals`` entry point."""
    raise SystemExit(main())
