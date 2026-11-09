"""The validator's evaluations: its verdicts on the golden set, and beside the reference.

The reference is the published artefacts applied as published, as the EU's reference
validators compose them: the UBL 2.1 schema, then EN 16931's Schematron (with Peppol's for
the Peppol profile), nothing set aside and no rule of SEF Kopilot's own. The validator's
profiles differ from it on purpose in two ways: they set aside what a profile widens, and they
compute CEN's calculation rules again in Python (ADR-0007, ADR-0008). Judged under EN 16931
or Peppol, a document must still get the reference's verdict, and the same fatal rules outside
``ext:UBLExtensions``. Inside it, CEN's stylesheet applies its rules to the Serbian extension's
copies of the totals, which are none of EN 16931's business groups: the reference reports the
calculation rules there, which the validator computes on the real totals only (ADR-0007).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from einvoice_core.pipeline import PROFILES, ValidationReport, validate
from einvoice_core.schematron import validate_schematron
from einvoice_core.violations import Severity, Violation, is_valid
from einvoice_core.xml import ParseError, load_document
from einvoice_core.xsd import validate_xsd
from sef_evals.golden import Case
from sef_evals.measures import Measure

__all__ = ["REFERENCE_PROFILES", "Reference", "measure", "reference"]

#: The profile under which a case's document is compared with the reference. SRB-CIUS has no
#: published reference: its documents are compared under EN 16931, which it restricts.
REFERENCE_PROFILES: dict[str, str] = {"srb": "en16931", "en16931": "en16931", "peppol": "peppol"}

#: Enough to list every violation of any document of the corpus, so that none is left uncounted.
_MAX_VIOLATIONS = 100_000
#: Where the reference judges what EN 16931 does not model (ADR-0007).
_EXTENSION = "/ext:UBLExtensions"


@dataclass(frozen=True)
class Reference:
    """The reference's verdict on a document, and the fatal rules it reports outside
    ``ext:UBLExtensions``, with how often."""

    valid: bool
    fatal: Counter[str]


def _fatal(violations: Iterable[Violation]) -> Counter[str]:
    return Counter(v.rule_id for v in violations if v.severity is Severity.FATAL)


def _outside(violations: Iterable[Violation]) -> Iterable[Violation]:
    """The violations that are not located inside ``ext:UBLExtensions``."""
    return (v for v in violations if v.xpath is None or _EXTENSION not in v.xpath)


def reference(path: Path, profile: str) -> Reference:
    """The reference's verdict on the document at ``path``, under ``profile``'s rule sets."""
    try:
        tree = load_document(path)
    except ParseError:
        return Reference(valid=False, fatal=Counter({"XML": 1}))
    schema = validate_xsd(tree)
    if not is_valid(schema):
        return Reference(valid=False, fatal=_fatal(schema))
    found = validate_schematron(tree, PROFILES[profile].rule_sets)
    return Reference(valid=is_valid(found), fatal=_fatal(_outside(found)))


def _said(valid: bool) -> str:
    return "accepts" if valid else "rejects"


def _rules(counted: Counter[str]) -> str:
    return ", ".join(f"{r} ({n})" if n > 1 else r for r, n in sorted(counted.items())) or "none"


def measure(root: Path, cases: Sequence[Case]) -> list[Measure]:
    """The validator's measures on ``cases``: agreement with the reference, verdicts and the
    rules that must be reported."""

    @cache
    def report(document: str, profile: str) -> ValidationReport:
        return validate(root / document, profile, max_violations=_MAX_VIOLATIONS)

    @cache
    def referenced(document: str, profile: str) -> Reference:
        return reference(root / document, profile)

    compared = sorted({(case.document, REFERENCE_PROFILES[case.profile]) for case in cases})
    disagreements = []
    rule_differences = []
    for document, profile in compared:
        ours, theirs = report(document, profile), referenced(document, profile)
        if ours.valid != theirs.valid:
            disagreements.append(
                f"{document} [{profile}]: the reference {_said(theirs.valid)} it, "
                f"the validator {_said(ours.valid)} it"
            )
        if (fatal := _fatal(_outside(ours.violations))) != theirs.fatal:
            rule_differences.append(
                f"{document} [{profile}]: the validator reports {_rules(fatal - theirs.fatal)} "
                f"more, {_rules(theirs.fatal - fatal)} fewer than the reference"
            )

    rejects = [case for case in cases if case.expect == "reject"]
    accepts = [case for case in cases if case.expect == "accept"]
    named = [case for case in cases if case.reports]
    missed = []
    for case in named:
        reported = Counter(v.rule_id for v in report(case.document, case.profile).violations)
        if missing := case.reports - reported:
            missed.append(f"{case.id}: {_rules(missing)} not reported")

    return [
        Measure(
            name="agreement",
            title="Documents on which the validator's verdict is the reference's",
            kind="share",
            total=len(compared),
            failures=tuple(disagreements),
        ),
        Measure(
            name="rule_agreement",
            title="Documents on which the validator reports the reference's fatal rules",
            kind="share",
            total=len(compared),
            failures=tuple(rule_differences),
        ),
        Measure(
            name="false_accept_rate",
            title="Documents that must be rejected, accepted",
            kind="rate",
            total=len(rejects),
            failures=tuple(
                f"{case.id}: accepted"
                for case in rejects
                if report(case.document, case.profile).valid
            ),
        ),
        Measure(
            name="false_reject_rate",
            title="Documents that must be accepted, rejected",
            kind="rate",
            total=len(accepts),
            failures=tuple(
                f"{case.id}: rejected for "
                f"{_rules(_fatal(report(case.document, case.profile).violations))}"
                for case in accepts
                if not report(case.document, case.profile).valid
            ),
        ),
        Measure(
            name="detection",
            title="Documents whose mistake is reported by the rules it must be reported by",
            kind="share",
            total=len(named),
            failures=tuple(missed),
        ),
    ]
