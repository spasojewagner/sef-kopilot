"""Schematron validation: the EN 16931 business rules, executed with Saxon.

The second layer of the deterministic validator checks the business rules that the standards
publish as Schematron: the EN 16931 core rules (``BR-*``, ``BR-CO-*``, the code-list rules
``BR-CL-*``) with the UBL syntax-binding rules (``UBL-*``). The rules run exactly as published;
none of them is re-implemented or edited.

How it works:

* A rule set is an **official compiled XSLT**: CEN/TC 434 publishes one for EN 16931.
* Saxon-HE (``saxonche``) compiles each stylesheet once per process (:func:`default_validator`
  is cached) and applies it to the document. The result is an SVRL report; every
  ``failed-assert`` and ``successful-report`` in it becomes a
  :class:`~einvoice_core.violations.Violation` carrying the rule's ``id``, ``flag`` and text.
* SVRL locations are written in the "full path" notation of the stylesheet generator
  (``/*:Invoice[namespace-uri()='…'][1]/*:InvoiceLine[namespace-uri()='…'][2]``). They are
  resolved step by step against the document and rendered as canonical XPaths, or ``null``
  when they cannot be resolved with certainty.

The rule sets assume a schema-valid document: an XPath cast of a malformed amount raises a
dynamic error instead of failing an assertion. Apply them only to documents that passed the
XSD layer; a dynamic error surfaces as :class:`SchematronError`.

All Saxon calls share one lock. An XSLT executable carries per-call state (the global context
item, parameters), so concurrent use of a shared executable is serialised; transforming a
typical invoice takes milliseconds, so the lock is not a bottleneck at the expected load.
"""

from __future__ import annotations

import functools
import re
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from lxml import etree
from saxonche import PySaxonApiError, PySaxonProcessor, PyXslt30Processor, PyXsltExecutable

from einvoice_core.rulesets import ruleset_path, rulesets_dir
from einvoice_core.violations import Severity, Violation
from einvoice_core.xml import ParseError, canonical_xpath, load_document

__all__ = [
    "RULE_ID",
    "RULE_SETS",
    "SVRL",
    "RuleSet",
    "SchematronError",
    "SchematronValidator",
    "default_validator",
    "validate_schematron",
]

SVRL: Final = "http://purl.oclc.org/dsdl/svrl"
#: ``rule_id`` of a violation whose rule carries no ``id`` (no rule in the pinned sets lacks one).
RULE_ID: Final = "SCHEMATRON"

#: Documents are handed to Saxon as UTF-8 text; reports come back in the UTF-8 that the
#: stylesheets declare, which is also how saxonche decodes them.
_ENCODING: Final = "UTF-8"
#: Upper bound on the SVRL report parsed back; reports grow with the number of violations.
_MAX_REPORT_BYTES: Final = 64 * 1024 * 1024

_NAME: Final = r"[\w.-]+"
_STEP: Final = re.compile(
    rf"/\*:(?P<local>{_NAME})\[namespace-uri\(\)='(?P<uri>[^']*)'\]\[(?P<position>\d+)\]"
    rf"|/(?P<name>{_NAME})\[(?P<plain_position>\d+)\]"
    rf"|/@(?P<attribute>{_NAME})"
    rf"|/@\*\[local-name\(\)='(?P<attribute_local>{_NAME})' and "
    rf"namespace-uri\(\)='(?P<attribute_uri>[^']*)'\]"
)


class SchematronError(RuntimeError):
    """A rule set could not be compiled, or failed while being applied to a document.

    The message can quote document content (Saxon's text for a dynamic error names the value
    it could not convert), so like a violation it goes back to the caller and is never logged.
    """


@dataclass(frozen=True)
class RuleSet:
    """A Schematron rule set: one file inside a fetched third-party package."""

    name: str
    package: str
    """The entry in ``third_party/manifest.json`` whose directory contains ``path``."""
    path: str
    """Location of the compiled ``.xslt`` stylesheet inside the package."""
    description: str


RULE_SETS: Final[dict[str, RuleSet]] = {
    rule_set.name: rule_set
    for rule_set in (
        RuleSet(
            name="en16931",
            package="en16931",
            path="ubl/xslt/EN16931-UBL-validation.xslt",
            description="EN 16931 rules for UBL: the compiled XSLT published by CEN/TC 434.",
        ),
    )
}

_saxon_lock = threading.Lock()


@functools.cache
def _processor() -> PySaxonProcessor:
    """The process-wide Saxon processor; only called while holding ``_saxon_lock``."""
    return PySaxonProcessor(license=False)


@functools.cache
def _xslt_processor() -> PyXslt30Processor:
    """The process-wide XSLT 3.0 compiler; only called while holding ``_saxon_lock``."""
    return _processor().new_xslt30_processor()


def _compile(origin: Path, **stylesheet: str) -> PyXsltExecutable:
    with _saxon_lock:
        try:
            return _xslt_processor().compile_stylesheet(**stylesheet)
        except PySaxonApiError as error:
            raise SchematronError(f"cannot compile the stylesheet of {origin}: {error}") from error


def _element_at(steps: list[re.Match[str]], root: etree._Element) -> etree._Element | None:
    """The element that a sequence of full-path element steps designates, if it exists."""
    element: etree._Element | None = None
    for step in steps:
        position = int(step["position"] or step["plain_position"] or 0)
        if position < 1:
            return None  # an attribute step that is not the last step, or position 0
        tag = f"{{{step['uri']}}}{step['local']}" if step["local"] else step["name"]
        candidates = [root] if element is None else list(element)
        same = [candidate for candidate in candidates if candidate.tag == tag]
        if position > len(same):
            return None
        element = same[position - 1]
    return element


def _locate(location: str, root: etree._Element) -> tuple[str | None, int | None]:
    """Canonical XPath and source line of the node an SVRL location designates.

    Returns ``(None, None)`` unless the location consists of full-path steps only and every
    step matches a node of the document, and ``(None, line)`` for a namespace-qualified
    attribute, which has no canonical path (the attributes of UBL are unqualified).
    """
    steps = list(_STEP.finditer(location))
    if not steps or "".join(step[0] for step in steps) != location:
        return None, None
    last = steps[-1]
    is_attribute = bool(last["attribute"] or last["attribute_local"])
    element = _element_at(steps[:-1] if is_attribute else steps, root)
    if element is None:
        return None, None
    xpath, line = canonical_xpath(element), element.sourceline
    if not is_attribute:
        return xpath, line
    if last["attribute"]:
        found = last["attribute"] in element.attrib
        return (f"{xpath}/@{last['attribute']}", line) if found else (None, None)
    qualified = f"{{{last['attribute_uri']}}}{last['attribute_local']}"
    return (None, line) if qualified in element.attrib else (None, None)


def _violations(report: str, root: etree._Element) -> tuple[Violation, ...]:
    """The violations listed in an SVRL report, in report order.

    A missing ``flag`` counts as fatal: an assertion states a requirement.
    """
    try:
        svrl = load_document(report.encode(_ENCODING), max_bytes=_MAX_REPORT_BYTES).getroot()
    except ParseError as error:
        raise SchematronError(f"unreadable SVRL report: {error}") from error
    violations = []
    for entry in svrl.iter(f"{{{SVRL}}}failed-assert", f"{{{SVRL}}}successful-report"):
        xpath, line = _locate(entry.get("location", ""), root)
        text = entry.find(f"{{{SVRL}}}text")
        violations.append(
            Violation(
                rule_id=entry.get("id") or RULE_ID,
                severity=Severity.WARNING if entry.get("flag") == "warning" else Severity.FATAL,
                message=" ".join("".join(text.itertext()).split()) if text is not None else "",
                xpath=xpath,
                layer="schematron",
                line=line,
            )
        )
    return tuple(violations)


class SchematronValidator:
    """Applies one rule set to documents; the stylesheet is compiled when constructed.

    An instance can be shared between threads (Saxon calls are serialised, see the module
    documentation).
    """

    def __init__(self, rule_set: RuleSet, *, root: Path | None = None) -> None:
        self.rule_set = rule_set
        base = rulesets_dir() if root is None else root
        source = ruleset_path(rule_set.package, root=base) / rule_set.path
        if not source.is_file():
            raise SchematronError(f"rule set {rule_set.name!r}: {source} does not exist")
        self._executable = _compile(source, stylesheet_file=str(source))

    def validate(self, tree: etree._ElementTree) -> tuple[Violation, ...]:
        """The violations the rule set reports for the document, in report order."""
        document = etree.tostring(tree, encoding="unicode")
        with _saxon_lock:
            try:
                node = _processor().parse_xml(xml_text=document, encoding=_ENCODING)
                self._executable.set_global_context_item(xdm_item=node)
                report = self._executable.transform_to_string(xdm_node=node)
            except PySaxonApiError as error:
                raise SchematronError(f"rule set {self.rule_set.name!r} failed: {error}") from error
        if not report:
            raise SchematronError(f"rule set {self.rule_set.name!r} produced no report")
        return _violations(report, tree.getroot())


@functools.cache
def default_validator(name: str) -> SchematronValidator:
    """The process-wide validator for one of the :data:`RULE_SETS`, compiled on first use."""
    try:
        rule_set = RULE_SETS[name]
    except KeyError:
        known = ", ".join(sorted(RULE_SETS))
        raise SchematronError(f"unknown rule set {name!r}; known rule sets: {known}") from None
    return SchematronValidator(rule_set)


def validate_schematron(
    tree: etree._ElementTree, rule_sets: Iterable[str]
) -> tuple[Violation, ...]:
    """Apply the named rule sets in order and return their violations, concatenated."""
    return tuple(
        violation for name in rule_sets for violation in default_validator(name).validate(tree)
    )
