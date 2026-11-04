"""``einvoice``: validate e-invoices from the command line (ADR-0009).

    einvoice validate PATH [PATH ...] [--profile srb|en16931|peppol] [--format text|json]
    einvoice rules [--profile srb|en16931|peppol] [--format text|json]
    einvoice --version

A PATH is a file, a directory (the ``.xml`` files under it) or a pattern such as ``*.xml``,
expanded here when the shell has not done it (cmd and PowerShell pass patterns on as typed).

Exit status: 0 when every document is valid (warnings allowed), 1 when at least one is not,
2 for a usage error, a path that names no document or cannot be opened, or rule sets that have
not been fetched.

Messages may quote values from the documents; they go to standard output only, never to a log.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final, TextIO

from einvoice_core import __version__
from einvoice_core.arithmetic import RULE_IDS as CALCULATION_RULES
from einvoice_core.pipeline import (
    DEFAULT_MAX_VIOLATIONS,
    PROFILES,
    Profile,
    ValidationReport,
    validate,
)
from einvoice_core.rulesets import ENV_VAR, RulesetNotFoundError
from einvoice_core.srb import RULES
from einvoice_core.violations import Severity

__all__ = ["EXIT_ERROR", "EXIT_INVALID", "EXIT_VALID", "main"]

EXIT_VALID: Final = 0
EXIT_INVALID: Final = 1
EXIT_ERROR: Final = 2


_PATTERN = re.compile(r"[*?[]")


class _NoDocumentsError(Exception):
    """A command-line path that names no document."""


def _positive(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="einvoice",
        description="Validate UBL 2.1 e-invoices against SRB-CIUS (SEF), EN 16931 and Peppol.",
    )
    parser.add_argument("--version", action="version", version=f"einvoice {__version__}")
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    validate_command = commands.add_parser(
        "validate",
        help="validate one or more invoices",
        description="Validate invoices and credit notes; exit 0 if all are valid, 1 if not.",
    )
    validate_command.add_argument(
        "paths",
        nargs="+",
        type=Path,
        metavar="PATH",
        help="a file, a directory (the .xml files under it) or a pattern such as *.xml",
    )
    _profile_and_format(validate_command)
    validate_command.add_argument(
        "--max-violations",
        type=_positive,
        default=DEFAULT_MAX_VIOLATIONS,
        metavar="N",
        help=f"list at most N violations per document (default {DEFAULT_MAX_VIOLATIONS})",
    )
    validate_command.add_argument(
        "--show-set-aside",
        action="store_true",
        help="list the published rules the profile does not apply, with the reason",
    )

    rules_command = commands.add_parser(
        "rules",
        help="list what a profile checks",
        description="List the rule sets, the SRB-CIUS rules and the set-asides of a profile.",
    )
    _profile_and_format(rules_command)
    return parser


def _profile_and_format(command: argparse.ArgumentParser) -> None:
    command.add_argument(
        "--profile", choices=tuple(PROFILES), default="srb", help="the profile (default srb)"
    )
    command.add_argument(
        "--format", choices=("text", "json"), default="text", help="output format (default text)"
    )


# --- validate ----------------------------------------------------------------------------------


def _xml_files(directory: Path) -> list[Path]:
    return sorted(
        Path(folder, name)
        for folder, _, names in os.walk(directory)
        for name in names
        if name.lower().endswith(".xml")
    )


def _documents(paths: Sequence[Path]) -> list[Path]:
    """The documents the command-line paths stand for, in order.

    A directory stands for the ``.xml`` files under it. A path that does not exist but holds
    ``*``, ``?`` or ``[`` is a pattern the shell left alone, expanded here. Anything else is a
    file, opened when it is validated.
    """
    documents: list[Path] = []
    for path in paths:
        if path.is_dir():
            found = _xml_files(path)
            if not found:
                raise _NoDocumentsError(f"no .xml file in {path}")
        elif not path.exists() and _PATTERN.search(str(path)):
            matches = [Path(match) for match in sorted(glob.glob(str(path), recursive=True))]
            found = [
                document
                for match in matches
                for document in (_xml_files(match) if match.is_dir() else [match])
            ]
            if not found:
                raise _NoDocumentsError(f"nothing matches {path}")
        else:
            found = [path]
        documents += found
    return documents


def _text_report(name: str, report: ValidationReport, show_set_aside: bool) -> list[str]:
    fatal = sum(v.severity is Severity.FATAL for v in report.violations)
    warnings = len(report.violations) - fatal
    verdict = "valid" if report.valid else "invalid"
    counts = []
    if fatal:
        counts.append(f"{fatal} fatal")
    if warnings:
        counts.append(f"{warnings} warning{'s' if warnings != 1 else ''}")
    lines = [f"{name}: {verdict} ({report.profile})" + (f": {', '.join(counts)}" if counts else "")]
    for violation in report.violations:
        where = " ".join(
            part
            for part in (
                f"line {violation.line}" if violation.line is not None else "",
                violation.xpath or "",
            )
            if part
        )
        lines.append(f"  {violation.severity:<8} {violation.rule_id:<10} {where}".rstrip())
        lines.append(f"           {violation.message}")
    if report.omitted:
        lines.append(f"  ... {report.omitted} more not listed (--max-violations)")
    if report.set_aside and show_set_aside:
        for item in report.set_aside:
            instead = f" (checked by {', '.join(item.replaced_by)})" if item.replaced_by else ""
            lines.append(f"  set aside {item.violation.rule_id:<10} {item.violation.xpath or ''}")
            lines.append(f"           {item.reason}{instead}")
    elif report.set_aside:
        lines.append(
            f"  {len(report.set_aside)} published rule report(s) set aside by the "
            f"{report.profile} profile (--show-set-aside lists them)"
        )
    not_run = [outcome for outcome in report.layers if not outcome.ran]
    for note in dict.fromkeys(outcome.note for outcome in not_run):
        layers = ", ".join(outcome.layer for outcome in not_run if outcome.note == note)
        lines.append(f"  not run: {layers} ({note})")
    return lines


def _validate(arguments: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    try:
        documents = _documents(arguments.paths)
    except _NoDocumentsError as error:
        err.write(f"einvoice: {error}\n")
        return EXIT_ERROR
    results: list[tuple[Path, ValidationReport]] = []
    for path in documents:
        try:
            report = validate(str(path), arguments.profile, max_violations=arguments.max_violations)
        except RulesetNotFoundError as error:
            err.write(
                f"einvoice: {error}\nFetch the rule sets with `make rulesets` (or `uv run python "
                f"scripts/fetch_rulesets.py`), or point {ENV_VAR} at a directory that has them.\n"
            )
            return EXIT_ERROR
        except OSError as error:
            err.write(f"einvoice: cannot read {path}: {error.strerror or error}\n")
            return EXIT_ERROR
        results.append((path, report))
        if arguments.format == "text":  # as each document is judged
            out.write("\n".join(_text_report(str(path), report, arguments.show_set_aside)) + "\n")
    if arguments.format == "json":
        reports = [
            {"file": str(path), "report": report.model_dump(mode="json")}
            for path, report in results
        ]
        out.write(json.dumps(reports, indent=2) + "\n")
    elif len(results) > 1:
        valid = sum(report.valid for _, report in results)
        out.write(f"{len(results)} documents: {valid} valid, {len(results) - valid} invalid\n")
    return EXIT_VALID if all(report.valid for _, report in results) else EXIT_INVALID


# --- rules -------------------------------------------------------------------------------------


def _rules_data(profile: Profile) -> dict[str, Any]:
    return {
        "profile": profile.name,
        "title": profile.title,
        "rule_sets": list(profile.rule_sets),
        "srb_rules": [
            {
                "id": rule.id,
                "severity": str(rule.severity),
                "title": rule.title,
                "terms": list(rule.terms),
                "references": [
                    {"document": reference.document, "passage": reference.passage}
                    for reference in rule.references
                ],
            }
            for rule in (RULES if profile.srb_rules else ())
        ],
        "calculation_rules": list(CALCULATION_RULES),
        "set_aside": [
            {
                "rule_ids": None if entry.rule_ids is None else sorted(entry.rule_ids),
                "conditional": entry.when is not None,
                "reason": entry.reason,
                "replaced_by": list(entry.replaced_by),
            }
            for entry in profile.set_aside
        ],
    }


def _rules(arguments: argparse.Namespace, out: TextIO) -> int:
    data = _rules_data(PROFILES[arguments.profile])
    if arguments.format == "json":
        out.write(json.dumps(data, indent=2) + "\n")
        return EXIT_VALID
    lines = [
        f"{data['profile']}: {data['title']}",
        f"Schematron rule sets: {', '.join(data['rule_sets'])}",
        f"Calculation rules (arithmetic layer): {', '.join(data['calculation_rules'])}",
    ]
    if data["srb_rules"]:
        lines.append(f"SRB-CIUS rules ({len(data['srb_rules'])}):")
        lines += [
            f"  {rule['id']}  {rule['severity']:<8} {rule['title']} ({', '.join(rule['terms'])})"
            for rule in data["srb_rules"]
        ]
    lines.append("Published rules set aside:")
    for entry in data["set_aside"]:
        rules = "any rule" if entry["rule_ids"] is None else ", ".join(entry["rule_ids"])
        condition = ", in some cases" if entry["conditional"] else ""
        replacing = entry["replaced_by"]
        if set(replacing) == set(entry["rule_ids"] or ()):  # the same rules, computed again
            replacing = []
        instead = f" (checked by {', '.join(replacing)})" if replacing else ""
        lines.append(f"  {rules}{condition}: {entry['reason']}{instead}")
    out.write("\n".join(lines) + "\n")
    return EXIT_VALID


# --- entry point -------------------------------------------------------------------------------


def main(
    argv: Sequence[str] | None = None,
    *,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Run the command line; returns the exit status (``argparse`` exits on usage errors)."""
    arguments = build_parser().parse_args(argv)
    out = out if out is not None else sys.stdout
    err = err if err is not None else sys.stderr
    if arguments.command == "validate":
        return _validate(arguments, out, err)
    return _rules(arguments, out)


def console() -> None:
    """The ``einvoice`` console script: characters a terminal cannot show are replaced."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")
    raise SystemExit(main())


if __name__ == "__main__":  # pragma: no cover
    console()
