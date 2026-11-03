"""The shape of an SRB-CIUS rule and the document view rules are evaluated against.

A rule is plain data plus one function: an identifier (``SRB-001`` …), a one-line title, the
business terms it concerns, the passages of the official documents it is authored from, a
severity, and ``check(document)``, which yields a :class:`Finding` for every breach. Rules live
one per module in :mod:`einvoice_core.srb.rules` (ADR-0006).

Rules read the typed model (:class:`einvoice_core.model.Invoice`) where it carries the
business term, and the XML tree where the rule is about syntax the model does not keep, such
as a ``schemeID`` that must be absent or the tax scheme a party tax registration is filed
under. Findings point at an element of the tree, so violations get canonical XPaths and source
lines like every other layer.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Final

from lxml import etree

from einvoice_core import model
from einvoice_core.violations import Severity
from einvoice_core.xml import NAMESPACES

__all__ = ["NAMESPACES_SRB", "Document", "Finding", "Reference", "Rule"]

#: Prefixes available to rules: the canonical UBL prefixes plus the SRB-CIUS extension.
NAMESPACES_SRB: Final = {**NAMESPACES, "sbt": "http://mfin.gov.rs/srbdt/srbdtext"}


@dataclass(frozen=True)
class Reference:
    """A passage of an official document that a rule is authored from."""

    document: str
    """Key of the document in :data:`einvoice_core.srb.sources.SOURCES`."""
    passage: str
    """Where in the document, e.g. ``"1.3, Table 1, BT-3"``."""


@dataclass(frozen=True)
class Finding:
    """One breach of a rule: what is wrong, and the element it is about."""

    message: str
    """English text stating the requirement and, where useful, the offending value."""
    element: etree._Element | None = None
    """The element to point at; ``None`` when the problem is the document as a whole."""
    attribute: str | None = None
    """An unqualified attribute of ``element`` that is the actual problem (``schemeID``)."""


@dataclass(frozen=True)
class Document:
    """What a rule sees: the parsed tree and the typed model built from it."""

    tree: etree._ElementTree
    invoice: model.Invoice

    @property
    def root(self) -> etree._Element:
        return self.tree.getroot()

    def find_all(self, path: str, context: etree._Element | None = None) -> list[etree._Element]:
        """Elements matching ``path`` (with the prefixes of :data:`NAMESPACES_SRB`)."""
        found = (self.root if context is None else context).xpath(path, namespaces=NAMESPACES_SRB)
        if not isinstance(found, list):
            return []
        return [node for node in found if isinstance(node, etree._Element)]

    def find(self, path: str, context: etree._Element | None = None) -> etree._Element | None:
        """The first element matching ``path``, if any."""
        found = self.find_all(path, context)
        return found[0] if found else None


@dataclass(frozen=True)
class Rule:
    """One SRB-CIUS rule."""

    id: str
    title: str
    terms: tuple[str, ...]
    """The EN 16931 business terms and groups the rule concerns (``BT-3``, ``BG-4``)."""
    references: tuple[Reference, ...]
    check: Callable[[Document], Iterable[Finding]]
    severity: Severity = Severity.FATAL
