"""One validation, as the validator's process runs it: the work and its outcome as data.

:func:`outcome` is what a validator runs for each document, in its child process or in a
thread (:mod:`sef_api.invoices.validator`). It never raises: what is wrong with the document
is the report, and what goes wrong with the validation is a kind of outcome that carries no
document content, so that it can cross a process boundary and be logged.

Before the validation proper, the elements of the document are counted, without building it,
by a parser as hardened as the validator's own. The cost of validating grows with elements,
not bytes (an embedded PDF is one text node), so a budget of elements bounds the memory and
the time one document can take.
"""

from __future__ import annotations

import io
from typing import Final, Literal

from lxml import etree

from einvoice_core import schematron, xsd
from einvoice_core.pipeline import PROFILES, validate
from einvoice_core.rulesets import RulesetNotFoundError, ruleset_path
from einvoice_core.schematron import SchematronError

__all__ = [
    "Kind",
    "Outcome",
    "ProfileName",
    "count_elements",
    "outcome",
    "rule_sets_missing",
    "warm_up",
]

#: The profiles a document can be validated against (``einvoice_core.pipeline.PROFILES``).
ProfileName = Literal["srb", "en16931", "peppol"]

#: ``report``: the validator's report as JSON. ``too-many-elements``: the document has more
#: elements than the budget allows. ``unavailable``: the rule sets are missing or broken.
#: ``refused``: the rule sets could not be applied to this document. ``failed``: anything
#: else, by the type of the exception only.
Kind = Literal["report", "too-many-elements", "unavailable", "refused", "failed"]
Outcome = tuple[Kind, str]

_EVENTS: Final = ("end",)


def _packages() -> list[str]:
    """Every fetched package the profiles need: the UBL schemas, the Schematron rule sets and
    the compiler for the rule sets published only as Schematron sources."""
    rule_sets = {name for profile in PROFILES.values() for name in profile.rule_sets}
    packages = {schematron.RULE_SETS[name].package for name in rule_sets}
    return [xsd.UBL_RULESET, *sorted(packages), schematron.COMPILER_PACKAGE]


def rule_sets_missing() -> str | None:
    """Why this server cannot validate, a rule set that has not been fetched, or None."""
    try:
        for package in _packages():
            ruleset_path(package)
    except RulesetNotFoundError as missing:
        return str(missing)
    return None


def warm_up() -> str | None:
    """Compile the UBL schemas and every profile's rule sets now rather than on first use.

    Returns why the validator cannot run, or None. Only the type of an unexpected error is
    kept: its message is not needed to see that the rule sets are broken.
    """
    missing = rule_sets_missing()
    if missing is not None:
        return missing
    try:
        xsd.default_validator()
        for name in sorted({name for profile in PROFILES.values() for name in profile.rule_sets}):
            schematron.default_validator(name)
    except Exception as error:
        return f"the validator's rule sets cannot be loaded ({type(error).__name__})"
    return None


def count_elements(content: bytes, *, limit: int) -> int:
    """The elements of ``content``, counted while it is read and never built, up to ``limit``
    plus one. Malformed XML counts what was read before it: the validator reports it."""
    parser = etree.iterparse(
        io.BytesIO(content),
        events=_EVENTS,
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        huge_tree=False,
    )
    counted = 0
    try:
        for _event, element in parser:
            counted += 1
            if counted > limit:
                break
            element.clear(keep_tail=True)  # what has been counted is not kept
            while (previous := element.getprevious()) is not None:
                parent = element.getparent()
                if parent is None:
                    break
                parent.remove(previous)
    except etree.XMLSyntaxError:
        pass
    return counted


def outcome(content: bytes, profile: ProfileName, *, max_elements: int) -> Outcome:
    """Validate ``content`` under ``profile``, if it has at most ``max_elements`` elements."""
    if count_elements(content, limit=max_elements) > max_elements:
        return "too-many-elements", f"the invoice has more than {max_elements} elements"
    try:
        report = validate(content, profile)
    except RulesetNotFoundError:
        return "unavailable", "the validator's rule sets are not installed"
    except SchematronError:
        return "refused", "the rule sets could not be applied to this invoice"
    except Exception as error:
        return "failed", type(error).__name__
    return "report", report.model_dump_json()
