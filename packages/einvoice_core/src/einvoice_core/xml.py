"""Hardened XML loading and canonical XPath addressing.

Everything that touches raw bytes goes through :func:`load_document`, which configures lxml so
that an invoice can never make the parser fetch a network resource, expand entities or load a
DTD. Invoices do not need any of those features, and each of them is a classic attack vector
(XXE, billion laughs). The byte limit is a first line of defence against resource exhaustion;
the API layer applies its own, stricter, upload limits on top.

:func:`canonical_xpath` produces the XPath used throughout the system to point at a place in
the original document (violations, explanations, patches). It is deterministic, readable and
unambiguous: a positional predicate is added only where the element has same-named siblings.
Each layer addresses many elements of one document inside :func:`sibling_index`, so that the
work stays linear in the size of the document however many siblings an element has.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
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
    "child_element",
    "load_document",
    "qualified_name",
    "sibling_index",
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
        # Comments and processing instructions mean nothing in UBL. Dropping them leaves every
        # value one text node, which is how this code and the published rule sets read it.
        remove_comments=True,
        remove_pis=True,
        recover=False,  # malformed input is an error, never "repaired"
    )


def load_document(source: Source, *, max_bytes: int = DEFAULT_MAX_BYTES) -> etree._ElementTree:
    """Parse XML from bytes, a string path, a path-like object or a binary stream.

    Raises :class:`ParseError` for oversize input, malformed XML, or a document that
    declares a DOCTYPE (invoices never need one, and it is the entry point for entity
    attacks). A ``str`` is treated as a *path*, never as XML text, so that a caller cannot
    accidentally parse user-controlled text through the path branch.

    Comments and processing instructions are dropped. XML lets them sit inside a value:
    ``<cbc:PayableAmount>1<!-- -->2000.00</cbc:PayableAmount>`` is the amount ``12000.00``.
    Kept, they split the value into two text nodes, ``element.text`` reads ``1``, and a rule
    that reads ``text()`` fails or compares only a part. Dropped, the value is one node again.
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


class _Children:
    """The children of one element, grouped by name, with each one's place in its group."""

    __slots__ = ("named", "place")

    def __init__(self, parent: etree._Element) -> None:
        self.named: dict[object, list[etree._Element]] = {}
        self.place: dict[etree._Element, int] = {}
        for child in parent:
            same = self.named.setdefault(child.tag, [])
            same.append(child)
            self.place[child] = len(same)


#: The children of every element visited in the current :func:`sibling_index` block.
_INDEX: ContextVar[dict[etree._Element, _Children] | None] = ContextVar(
    "einvoice_core.xml.index", default=None
)


@contextmanager
def sibling_index() -> Iterator[None]:
    """Within the block, remember the children of every element once they are looked at.

    Finding where an element stands among its same-named siblings means reading all of them,
    so addressing each of a document's N invoice lines would read N siblings N times. Inside
    this block each element's children are read once, which keeps the work linear in the size
    of the document. It is a context manager and a decorator; nested blocks share the outer
    index, and leaving the outermost block forgets it. It must not be held across documents
    that change: the index describes the tree as it was read.
    """
    if _INDEX.get() is not None:
        yield
        return
    token = _INDEX.set({})
    try:
        yield
    finally:
        _INDEX.reset(token)


def _children(parent: etree._Element) -> _Children:
    index = _INDEX.get()
    if index is None:
        return _Children(parent)
    children = index.get(parent)
    if children is None:
        children = index[parent] = _Children(parent)
    return children


def child_element(parent: etree._Element, tag: str, position: int) -> etree._Element | None:
    """The ``position``-th child (from 1) of ``parent`` with ``tag`` (Clark notation), if any."""
    same = _children(parent).named.get(tag, [])
    return same[position - 1] if 0 < position <= len(same) else None


def canonical_xpath(element: etree._Element) -> str:
    """Absolute XPath of ``element`` with canonical prefixes and minimal positional predicates.

    ``/ubl:Invoice/cac:InvoiceLine[2]/cbc:ID``: the predicate appears only on steps whose
    element has siblings with the same name, so the expression always selects exactly one
    node and stays readable for the people who have to act on it. Called for many elements of
    one document, it should run inside :func:`sibling_index`.
    """
    steps: list[str] = []
    current: etree._Element | None = element
    while current is not None:
        step = qualified_name(current)
        parent = current.getparent()
        if parent is not None:
            children = _children(parent)
            if len(children.named[current.tag]) > 1:
                step = f"{step}[{children.place[current]}]"
        steps.append(step)
        current = parent
    return "/" + "/".join(reversed(steps))
