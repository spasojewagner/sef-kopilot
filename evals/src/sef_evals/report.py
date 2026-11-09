"""The report of a run: ``latest.json`` for machines, ``latest.md`` for people.

Both hold only what the run measured and the rule sets it measured with, never a time, a
machine or a version of the code, which the commit names: the same code and rule sets write
the same report, and a change in it shows up as a diff to review.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sef_evals.thresholds import Judgement

__all__ = ["JSON_NAME", "MARKDOWN_NAME", "as_json", "as_markdown", "versions"]

JSON_NAME = "latest.json"
MARKDOWN_NAME = "latest.md"

_COMMENT = (
    "Written by `make evals` (sef-evals, ADR-0054); do not edit. The measures of the latest "
    "run, each beside its threshold in evals/thresholds.yaml."
)


def versions(root: Path) -> dict[str, Any]:
    """The rule sets the run measured with, as ``third_party/manifest.json`` pins them."""
    manifest = json.loads((root / "third_party" / "manifest.json").read_text(encoding="utf-8"))
    pinned = {
        entry["name"]: entry.get("ref") or f"sha256:{entry['sha256'][:12]}"
        for entry in manifest["rulesets"]
    }
    return {"rule sets": pinned}


def _entry(judgement: Judgement) -> dict[str, Any]:
    entry: dict[str, Any] = {}
    if (measure := judgement.measure) is not None:
        entry |= {
            "title": measure.title,
            "kind": measure.kind,
            "value": None if measure.value is None else round(measure.value, 4),
            "passed": measure.passed,
            "total": measure.total,
        }
    if (threshold := judgement.threshold) is not None:
        entry["threshold"] = threshold.model_dump(exclude_none=True)
    entry["met"] = judgement.met
    if measure is not None:
        entry["failures"] = list(measure.failures)
    return entry


def as_json(judgements: Sequence[Judgement], measured: Mapping[str, Any]) -> str:
    report = {
        "$comment": _COMMENT,
        "measured": dict(measured),
        "met": all(j.met is not False for j in judgements),
        "measures": {judgement.name: _entry(judgement) for judgement in judgements},
    }
    return json.dumps(report, indent=2, ensure_ascii=False) + "\n"


def _value(judgement: Judgement) -> str:
    measure = judgement.measure
    if measure is None or measure.value is None:
        return "not measured"
    counted = measure.passed if measure.kind == "share" else len(measure.failures)
    return f"{measure.value:.1%} ({counted} of {measure.total})"


_MET = {True: "yes", False: "**no**", None: "—"}


def as_markdown(judgements: Sequence[Judgement], measured: Mapping[str, Any]) -> str:
    rule_sets = ", ".join(f"{name} {ref}" for name, ref in measured["rule sets"].items())
    model = ""
    if "model" in measured:
        recorded = measured["model"]
        model = (
            f", and the answers of {recorded} recorded in evals/cassettes/"
            if recorded is not None
            else ", with no answer of a language model recorded"
        )
    lines = [
        "# Evaluation report",
        "",
        "Written by `make evals` (ADR-0054); do not edit. Measured with the rule sets "
        f"{rule_sets}{model}.",
        "",
        "| Measure | What it counts | Value | Threshold | Met |",
        "| --- | --- | --- | --- | --- |",
    ]
    for judgement in judgements:
        title = judgement.measure.title if judgement.measure is not None else ""
        threshold = str(judgement.threshold) if judgement.threshold is not None else "—"
        lines.append(
            f"| `{judgement.name}` | {title} | {_value(judgement)} | {threshold} "
            f"| {_MET[judgement.met]} |"
        )
    for judgement in judgements:
        if (measure := judgement.measure) is not None and measure.failures:
            lines += ["", f"## `{judgement.name}`", ""]
            lines += [f"- {failure}" for failure in measure.failures]
    return "\n".join(lines) + "\n"
