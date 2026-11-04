"""Hardened XML loading and canonical XPath addressing.

Everything that touches raw bytes goes through :func:`load_document`, which configures lxml so
that an invoice can never make the parser fetch a network resource, expand entities or load a
DTD. Invoices do not need any of those features, and each of them is a classic attack vector
(XXE, billion laughs). The byte limit is a first line of defence against resource exhaustion;
the API layer applies its own, stricter, upload limits on top.

:func:`canonical_xpath` produces the XPath used throughout the system to point at a place in
the original document (violations, explanations, patches). It is deterministic, readable and
unambiguous: a positional predicate is added only where the element has same-named siblings.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import IO, Final

from lxml import etree

__all__ = [
    "CAC",
    "CBC",
    "CN",
    "DEFAULT_MAX_BYTES",
    "EXT",
    "NAMESPACES",
    "SRBDT_EXT",
    "UBL",
    "ParseError",
    "canonical_xpath",
    "load_document",
    "qualified_name",
]

UBL: Final = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
CN: Final = "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"
CAC: Final = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
CBC: Final = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
EXT: Final = "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2"
#: The Serbian extension of SRB-CIUS (``SrbDtExt`` inside ``ext:UBLExtensions``).
SRBDT_EXT: Final = "http://mfin.gov.rs/srbdt/srbdtext"

#: Canonical prefixes, usable directly with ``element.xpath(..., namespaces=NAMESPACES)``.
#: ``sbt`` is the prefix the Ministry of Finance uses for its extension in its own examples.
NAMESPACES: Final[dict[str, str]] = {
    "ubl": UBL,
    "cn": CN,
    "cac": CAC,
    "cbc": CBC,
    "ext": EXT,
    "sbt": SRBDT_EXT,
}
_PREFIX_BY_URI: Final[dict[str, str]] = {uri: prefix for prefix, uri in NAMESPACES.items()}

#: 10 MiB: far above any real invoice, far below what would trouble the process.
DEFAULT_MAX_BYTES: Final = 10 * 1024 * 1024

Source = bytes | bytearray | str | os.PathLike[str] | IO[bytes]


class ParseError(ValueError):
    """The input could not be turned into an invoice model.

    ``xpath`` points at the offending element when the problem is local to one element;
    it is ``None`` for document-level problems (malformed XML, forbidden constructs, size).
    """

    def __init__(self, message: str, *, xpath: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.xpath = xpath

    def __str__(self) -> str:
        return f"{self.message} (at {self.xpath})" if self.xpath else self.message


def _read_bytes(source: Source, max_bytes: int) -> bytes:
    """Read the source into memory, refusing anything larger than ``max_bytes``."""
    limit = max_bytes + 1  # read one byte more than allowed to detect oversize input
    if isinstance(source, bytes | bytearray):
        data = bytes(source)
    elif isinstance(source, str | os.PathLike):
        with Path(source).open("rb") as handle:
            data = handle.read(limit)
    else:
        data = source.read(limit)
    if len(data) > max_bytes:
        raise ParseError(f"document exceeds the size limit of {max_bytes} bytes")
    return data


def _parser() -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False,  # never expand entities, internal or external
        no_network=True,  # never fetch anything
        load_dtd=False,
        dtd_validation=False,
        attribute_defaults=False,
        huge_tree=False,  # keep libxml2's depth and size guards
        remove_comments=False,
        remove_pis=False,
        recover=False,  # malformed input is an error, never "repaired"
    )


def load_document(source: Source, *, max_bytes: int = DEFAULT_MAX_BYTES) -> etree._ElementTree:
    """Parse XML from bytes, a string path, a path-like object or a binary stream.

    Raises :class:`ParseError` for oversize input, malformed XML, or a document that
    declares a DOCTYPE (invoices never need one, and it is the entry point for entity
    attacks). A ``str`` is treated as a *path*, never as XML text, so that a caller cannot
    accidentally parse user-controlled text through the path branch.
    """
    data = _read_bytes(source, max_bytes)
    try:
        root = etree.fromstring(data, parser=_parser())
    except etree.XMLSyntaxError as error:
        raise ParseError(f"malformed XML: {error.msg}") from error
    tree = root.getroottree()
    if tree.docinfo.internalDTD is not None or tree.docinfo.externalDTD is not None:
        raise ParseError("documents with a DOCTYPE declaration are not accepted")
    return tree


def qualified_name(element: etree._Element) -> str:
    """``prefix:local`` using the canonical prefixes, falling back to the document's own."""
    qname = etree.QName(element)
    if not qname.namespace:
        return qname.localname
    prefix = _PREFIX_BY_URI.get(qname.namespace) or element.prefix
    return f"{prefix}:{qname.localname}" if prefix else f"{{{qname.namespace}}}{qname.localname}"


def canonical_xpath(element: etree._Element) -> str:
    """Absolute XPath of ``element`` with canonical prefixes and minimal positional predicates.

    ``/ubl:Invoice/cac:InvoiceLine[2]/cbc:ID``: the predicate appears only on steps whose
    element has siblings with the same name, so the expression always selects exactly one
    node and stays readable for the people who have to act on it.
    """
    steps: list[str] = []
    current: etree._Element | None = element
    while current is not None:
        step = qualified_name(current)
        parent = current.getparent()
        if parent is not None:
            same = [sibling for sibling in parent if sibling.tag == current.tag]
            if len(same) > 1:
                step = f"{step}[{same.index(current) + 1}]"
        steps.append(step)
        current = parent
    return "/" + "/".join(reversed(steps))
