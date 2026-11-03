"""Schematron validation: the EN 16931 and Peppol BIS business rules, executed with Saxon.

The second layer of the deterministic validator checks the business rules that the standards
publish as Schematron: the EN 16931 core rules (``BR-*``, ``BR-CO-*``, the code-list rules
``BR-CL-*``) with the UBL syntax-binding rules (``UBL-*``), and the Peppol BIS Billing 3.0 rules
(``PEPPOL-EN16931-*``, ``PEPPOL-COMMON-*``). The rules run exactly as published; none of them
is re-implemented or edited.

How it works:

* A rule set is either an **official compiled XSLT** (CEN/TC 434 publishes one for EN 16931)
  or a **Schematron source** (OpenPeppol publishes only ``.sch`` files). Sources are compiled
  to XSLT with the ISO Schematron reference implementation (the pinned ``iso-schematron``
  package). The result is cached in ``_compiled/`` next to the fetched rule sets, under a name
  derived from the digests of the source files and of the compiler, so a stale compilation is
  never reused.
* Saxon-HE (``saxonche``) compiles each stylesheet once per process (:func:`default_validator`
  is cached) and applies it to the document. The result is an SVRL report; every
  ``failed-assert`` and ``successful-report`` in it becomes a
  :class:`~einvoice_core.violations.Violation` carrying the rule's ``id``, ``flag`` and text.
* SVRL locations are written in the compiler's "full path" notation
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

import contextlib
import functools
import hashlib
import json
import os
import re
import tempfile
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
    "CACHE_DIR",
    "COMPILER_PACKAGE",
    "RULE_ID",
    "RULE_SETS",
    "SVRL",
    "RuleSet",
    "SchematronError",
    "SchematronValidator",
    "compile_schematron",
    "default_validator",
    "validate_schematron",
]

SVRL: Final = "http://purl.oclc.org/dsdl/svrl"
#: The fetched package that holds the ISO Schematron compiler.
COMPILER_PACKAGE: Final = "iso-schematron"
#: Directory, under the rule-set root, for stylesheets compiled from Schematron sources.
CACHE_DIR: Final = "_compiled"
#: ``rule_id`` of a violation whose rule carries no ``id`` (no rule in the pinned sets lacks one).
RULE_ID: Final = "SCHEMATRON"

_COMPILER_DIR: Final = Path("trunk", "schematron", "code")
_COMPILER_PIPELINE: Final = (
    "iso_dsdl_include.xsl",  # resolve sch:include and sch:extends
    "iso_abstract_expand.xsl",  # instantiate abstract patterns
    "iso_svrl_for_xslt2.xsl",  # generate the SVRL-producing XSLT 2.0 stylesheet
)
#: The last pipeline step imports the skeleton, so the skeleton is part of the compiler too.
_COMPILER_FILES: Final = (*_COMPILER_PIPELINE, "iso_schematron_skeleton_for_saxon.xsl")
#: ``allow-foreign`` keeps the XSLT functions the Peppol rules define (``u:gln``, ``u:mod11``,
#: ...); ``fired-rule`` entries would only make the report larger.
_COMPILER_PARAMETERS: Final = {"allow-foreign": "true", "generate-fired-rule": "false"}
#: Documents are handed to Saxon as UTF-8 text; reports come back in the UTF-8 that every
#: stylesheet here declares, which is also how saxonche decodes them.
_ENCODING: Final = "UTF-8"
#: Upper bound on the SVRL report parsed back; reports grow with the number of violations.
_MAX_REPORT_BYTES: Final = 64 * 1024 * 1024
_CACHE_FILE_MODE: Final = 0o644

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
    """Location of the rule set inside the package: a ``.sch`` source or a compiled ``.xslt``."""
    description: str

    @property
    def is_source(self) -> bool:
        """Whether the rule set is a Schematron source that has to be compiled first."""
        return self.path.endswith(".sch")


RULE_SETS: Final[dict[str, RuleSet]] = {
    rule_set.name: rule_set
    for rule_set in (
        RuleSet(
            name="en16931",
            package="en16931",
            path="ubl/xslt/EN16931-UBL-validation.xslt",
            description="EN 16931 rules for UBL: the compiled XSLT published by CEN/TC 434.",
        ),
        RuleSet(
            name="en16931-peppol",
            package="peppol-bis-billing-3",
            path="rules/sch/CEN-EN16931-UBL.sch",
            description="EN 16931 rules for UBL in the version Peppol BIS Billing 3.0 bundles.",
        ),
        RuleSet(
            name="peppol",
            package="peppol-bis-billing-3",
            path="rules/sch/PEPPOL-EN16931-UBL.sch",
            description="Peppol BIS Billing 3.0 rules (PEPPOL-EN16931-*, PEPPOL-COMMON-*).",
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


def compile_schematron(source: Path, compiler_dir: Path) -> str:
    """Compile a Schematron source into an SVRL-producing XSLT 2.0 stylesheet (returned as text).

    This is the standard ISO pipeline: resolve inclusions, expand abstract patterns, generate
    the validating stylesheet. The first step reads the source from its file, so that relative
    inclusions resolve against the source's directory.
    """
    with _saxon_lock:
        processor = _processor()
        try:
            include, expand, generate = (
                _xslt_processor().compile_stylesheet(stylesheet_file=str(compiler_dir / name))
                for name in _COMPILER_PIPELINE
            )
            for name, value in _COMPILER_PARAMETERS.items():
                generate.set_parameter(name, processor.make_string_value(value))
            text = include.transform_to_string(source_file=str(source))
            for step in (expand, generate):
                if not text:
                    break
                node = processor.parse_xml(xml_text=text, encoding=_ENCODING)
                text = step.transform_to_string(xdm_node=node)
        except PySaxonApiError as error:
            raise SchematronError(f"cannot compile Schematron {source}: {error}") from error
    if not text:
        raise SchematronError(f"compiling Schematron {source} produced no stylesheet")
    return text


def _cache_file(rule_set: RuleSet, source: Path, compiler_dir: Path, root: Path) -> Path:
    """Where the stylesheet compiled from ``source`` is cached, named by what it depends on.

    The digest covers the compiler, its parameters and every file in the source's directory
    tree, which is where the inclusions of a Schematron source live (the EN 16931 source
    includes its abstract, binding and code-list patterns from subdirectories).
    """
    recipe = {
        "pipeline": _COMPILER_PIPELINE,
        "parameters": _COMPILER_PARAMETERS,
        "source": source.name,
    }
    inputs = {
        f"source/{path.relative_to(source.parent).as_posix()}": path
        for path in source.parent.rglob("*")
        if path.is_file()
    }
    inputs.update({f"compiler/{name}": compiler_dir / name for name in _COMPILER_FILES})
    digest = hashlib.sha256(json.dumps(recipe, sort_keys=True).encode())
    for label in sorted(inputs):
        digest.update(label.encode())
        digest.update(hashlib.sha256(inputs[label].read_bytes()).digest())
    return root / CACHE_DIR / f"{rule_set.name}-{digest.hexdigest()[:16]}.xslt"


def _store(path: Path, text: str) -> None:
    """Cache a compiled stylesheet. Written atomically; an unwritable directory is no error.

    The file is made world-readable (temporary files are private by default) so that a cache
    written while building a container image can be read by the user the service runs as;
    its content is public rule-set code.
    """
    with contextlib.suppress(OSError):
        path.parent.mkdir(exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete_on_close=False
        ) as partial:
            partial.write(text)
            partial.close()
            os.chmod(partial.name, _CACHE_FILE_MODE)
            os.replace(partial.name, path)


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
        if not rule_set.is_source:
            self._executable = _compile(source, stylesheet_file=str(source))
            return
        compiler_dir = ruleset_path(COMPILER_PACKAGE, root=base) / _COMPILER_DIR
        cached = _cache_file(rule_set, source, compiler_dir, base)
        if cached.is_file():
            self._executable = _compile(source, stylesheet_file=str(cached))
            return
        text = compile_schematron(source, compiler_dir)
        _store(cached, text)
        self._executable = _compile(source, stylesheet_text=text)

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
