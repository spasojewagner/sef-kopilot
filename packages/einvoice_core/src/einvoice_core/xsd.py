"""UBL 2.1 XML Schema validation: the first layer of the deterministic validator.

A UBL invoice that is not valid against the official OASIS schemas is rejected by SEF and by
every Peppol access point before any business rule is looked at, so this is the first check
the validator runs and the only one that is purely about syntax (element names, order,
cardinality, datatypes, required attributes such as ``currencyID``).

How it works:

* The Invoice and CreditNote schemas from the pinned ``ubl-2.1`` rule set are compiled once
  per process (:func:`default_validator` is cached) and reused for every document; compiling
  both takes well under a second, validating a typical invoice well under a millisecond.
* Schema imports are resolved by a resolver confined to the schema directory: a reference to a
  URL or to a file elsewhere is refused, so loading the schemas never touches the network.
* libxml2 reports each problem with an XPath in the document's own prefixes. That path is
  evaluated against the tree and turned into the canonical XPath used everywhere else, after
  checking that the element found is the one the message names; messages are rewritten with
  the canonical prefixes (``cbc:IssueDate`` instead of ``{urn:oasis:…}IssueDate``).

libxml2 reports the first content-model error inside an element and does not validate the rest
of that element's content, so fixing one schema error can reveal the next one. The repair loop
re-validates after every change for exactly this reason.
"""

from __future__ import annotations

import functools
import re
import threading
import urllib.parse
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Final

from lxml import etree

from einvoice_core.rulesets import ruleset_path
from einvoice_core.violations import Severity, Violation
from einvoice_core.xml import CN, NAMESPACES, UBL, canonical_xpath, qualified_name

if TYPE_CHECKING:
    from lxml.etree._docloader import _InputDocument

    from einvoice_core.model import DocumentType

__all__ = [
    "DEFAULT_MAX_VIOLATIONS",
    "RULE_ID",
    "SCHEMA_FILES",
    "TRUNCATED",
    "UBL_RULESET",
    "UNSUPPORTED_DOCUMENT",
    "SchemaLoadError",
    "XsdValidator",
    "default_validator",
    "load_schema",
    "validate_xsd",
]

UBL_RULESET: Final = "ubl-2.1"
RULE_ID: Final = "XSD"
#: ``code`` of the violation reported for a document that is neither an Invoice nor a CreditNote.
UNSUPPORTED_DOCUMENT: Final = "UNSUPPORTED_DOCUMENT"
#: ``code`` of the notice appended when more violations were found than are reported.
TRUNCATED: Final = "TRUNCATED"
#: Upper bound on the violations returned for one document; protects the API from documents
#: crafted to produce an enormous error list.
DEFAULT_MAX_VIOLATIONS: Final = 500

SCHEMA_FILES: Final[dict[DocumentType, str]] = {
    "Invoice": "xsd/maindoc/UBL-Invoice-2.1.xsd",
    "CreditNote": "xsd/maindoc/UBL-CreditNote-2.1.xsd",
}
_DOCUMENT_ELEMENTS: Final[dict[str, DocumentType]] = {
    f"{{{UBL}}}Invoice": "Invoice",
    f"{{{CN}}}CreditNote": "CreditNote",
}
_PREFIX_BY_URI: Final = {uri: prefix for prefix, uri in NAMESPACES.items()}
_CLARK_NAMESPACE: Final = re.compile(r"\{([^{}]+)\}")
_MESSAGE_SUBJECT: Final = re.compile(
    r"^Element '(?P<tag>[^']+)'(?:, attribute '(?P<attribute>[^']+)')?:"
)
_PLAIN_NAME: Final = re.compile(r"^[A-Za-z_][\w.-]*$")


class SchemaLoadError(RuntimeError):
    """The XML Schemas could not be loaded (missing files, or a refused reference)."""


def _local_path(url: str) -> Path | None:
    """The filesystem path a schema reference points to, or ``None`` for a network URL."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "file":
        return Path(urllib.request.url2pathname(parsed.path))
    if len(parsed.scheme) > 1:  # http, https, ftp, ... (a one-letter scheme is a drive letter)
        return None
    return Path(url)


class _ConfinedResolver(etree.Resolver):
    """Resolves schema imports and includes only to files inside one directory."""

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.root = root.resolve()
        self.refused: list[str] = []

    def resolve(
        self, system_url: str | None, public_id: str | None, context: object, /
    ) -> _InputDocument | None:
        reference = system_url or public_id or ""
        location = _local_path(reference)
        if location is None or not location.resolve().is_relative_to(self.root):
            self.refused.append(reference)
            raise SchemaLoadError(f"reference outside {self.root} refused: {reference}")
        return self.resolve_filename(str(location), context)


def load_schema(path: Path, root: Path) -> etree.XMLSchema:
    """Compile the XML Schema at ``path``; it and everything it imports must lie inside ``root``.

    The schema documents are parsed without network access, entity expansion or DTD loading,
    like invoices are; unlike invoices they may carry an internal DTD subset (the W3C XML
    Signature schema shipped with UBL does), which is ignored.
    """
    resolver = _ConfinedResolver(root)
    parser = etree.XMLParser(no_network=True, resolve_entities=False, load_dtd=False)
    parser.resolvers.add(resolver)
    try:
        return etree.XMLSchema(etree.parse(str(path), parser))
    except (OSError, etree.LxmlError) as error:
        detail = f"refused reference {resolver.refused[0]}" if resolver.refused else str(error)
        raise SchemaLoadError(f"cannot load XML Schema {path}: {detail}") from error


def _readable(message: str) -> str:
    """Rewrite ``{namespace-uri}`` prefixes of UBL names with the canonical prefixes."""

    def replace(match: re.Match[str]) -> str:
        prefix = _PREFIX_BY_URI.get(match[1])
        return f"{prefix}:" if prefix else match[0]

    return _CLARK_NAMESPACE.sub(replace, message.strip())


class _Locator:
    """Finds the element a libxml2 error refers to and returns its canonical XPath."""

    def __init__(self, tree: etree._ElementTree) -> None:
        self._tree = tree
        self._namespaces: dict[str, str] | None = None

    def _prefix_map(self) -> dict[str, str]:
        """Every prefix the document binds to exactly one namespace (the ones libxml2 prints)."""
        if self._namespaces is None:
            bindings: dict[str, set[str]] = {}
            for element in self._tree.iter():
                if isinstance(element.tag, str):
                    for prefix, uri in element.nsmap.items():
                        if prefix:
                            bindings.setdefault(prefix, set()).add(uri)
            self._namespaces = {
                prefix: next(iter(uris)) for prefix, uris in bindings.items() if len(uris) == 1
            }
        return self._namespaces

    def xpath(self, path: str | None, message: str) -> str | None:
        """Canonical XPath of the node a libxml2 ``path`` points to, if it is the one the
        ``message`` names; ``None`` when that cannot be established with certainty."""
        subject = _MESSAGE_SUBJECT.match(message)
        if not path or subject is None:
            return None
        try:
            found = self._tree.xpath(path, namespaces=self._prefix_map())
        except etree.LxmlError:
            return None
        if not isinstance(found, list) or len(found) != 1:
            return None
        element = found[0]
        if not isinstance(element, etree._Element) or element.tag != subject["tag"]:
            return None
        location = canonical_xpath(element)
        attribute = subject["attribute"]
        if attribute and _PLAIN_NAME.match(attribute):
            location += f"/@{attribute}"
        return location


def _violation(entry: etree._LogEntry, locator: _Locator) -> Violation:
    return Violation(
        rule_id=RULE_ID,
        severity=Severity.WARNING if entry.level == etree.ErrorLevels.WARNING else Severity.FATAL,
        message=_readable(entry.message),
        xpath=locator.xpath(entry.path, entry.message),
        layer="xsd",
        code=entry.type_name,
        line=entry.line or None,
    )


def _unsupported_document(root: etree._Element) -> Violation:
    return Violation(
        rule_id=RULE_ID,
        severity=Severity.FATAL,
        message=(
            f"The document element {qualified_name(root)} is neither a UBL 2.1 Invoice "
            "nor a UBL 2.1 CreditNote."
        ),
        xpath=canonical_xpath(root),
        layer="xsd",
        code=UNSUPPORTED_DOCUMENT,
        line=root.sourceline,
    )


def _truncation_notice(omitted: int) -> Violation:
    return Violation(
        rule_id=RULE_ID,
        severity=Severity.FATAL,
        message=(
            f"{omitted} further schema errors are not listed; correct the errors above and "
            "validate again."
        ),
        xpath=None,
        layer="xsd",
        code=TRUNCATED,
    )


class XsdValidator:
    """Validates UBL 2.1 Invoice and CreditNote documents against the official schemas.

    One instance compiles both schemas and can be shared between threads: validation runs
    under a lock because lxml keeps the error log on the schema object.
    """

    def __init__(self, schema_root: Path, *, max_violations: int = DEFAULT_MAX_VIOLATIONS) -> None:
        self.schema_root = schema_root
        self.max_violations = max_violations
        self._schemas = {
            document_type: load_schema(schema_root / relative, schema_root)
            for document_type, relative in SCHEMA_FILES.items()
        }
        self._lock = threading.Lock()

    def validate(self, tree: etree._ElementTree) -> tuple[Violation, ...]:
        """All schema violations of the document, in the order libxml2 found them."""
        root = tree.getroot()
        document_type = _DOCUMENT_ELEMENTS.get(root.tag) if isinstance(root.tag, str) else None
        if document_type is None:
            return (_unsupported_document(root),)
        schema = self._schemas[document_type]
        with self._lock:
            schema.validate(tree)
            entries = list(schema.error_log)
        locator = _Locator(tree)
        violations = [_violation(entry, locator) for entry in entries[: self.max_violations]]
        if len(entries) > self.max_violations:
            violations.append(_truncation_notice(len(entries) - self.max_violations))
        return tuple(violations)


@functools.cache
def default_validator() -> XsdValidator:
    """The process-wide validator for the fetched ``ubl-2.1`` rule set, compiled on first use."""
    return XsdValidator(ruleset_path(UBL_RULESET))


def validate_xsd(
    tree: etree._ElementTree, *, validator: XsdValidator | None = None
) -> tuple[Violation, ...]:
    """Validate a loaded document (see :func:`einvoice_core.xml.load_document`)."""
    return (validator if validator is not None else default_validator()).validate(tree)
