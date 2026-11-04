"""Shared helpers for the SRB-CIUS rule tests.

Every rule is tested against edits of one valid synthetic Serbian invoice: the unedited
document (or a valid variant) must satisfy the rule, and an edit that breaks the requirement
must make the rule report exactly what it should, where it should.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from einvoice_core.srb import Rule, validate_srb
from einvoice_core.violations import Violation
from einvoice_core.xml import NAMESPACES, load_document


class Case:
    """An editable copy of a synthetic invoice and the violations one rule reports for it."""

    def __init__(self, path: Path) -> None:
        self.tree = load_document(path)

    @property
    def root(self) -> etree._Element:
        return self.tree.getroot()

    def element(self, path: str) -> etree._Element:
        """The single element at ``path``, relative to the document element."""
        found = self.root.xpath(path, namespaces=NAMESPACES)
        assert isinstance(found, list), path
        (element,) = (node for node in found if isinstance(node, etree._Element))
        return element

    def set_text(self, path: str, text: str) -> Case:
        self.element(path).text = text
        return self

    def set_attribute(self, path: str, name: str, value: str | None) -> Case:
        element = self.element(path)
        if value is None:
            del element.attrib[name]
        else:
            element.set(name, value)
        return self

    def remove(self, path: str) -> Case:
        element = self.element(path)
        parent = element.getparent()
        assert parent is not None, path
        parent.remove(element)
        return self

    def insert(self, path: str, fragment: str, *, after: str | None = None) -> Case:
        """Insert an XML fragment (prefixes ``cac``/``cbc`` allowed) as a child of ``path``.

        The fragment goes after the child matching ``after``, or first when ``after`` is None.
        """
        declarations = " ".join(f'xmlns:{prefix}="{uri}"' for prefix, uri in NAMESPACES.items())
        new = etree.fromstring(f"<wrapper {declarations}>{fragment}</wrapper>")[0]
        parent = self.element(path)
        position = 0 if after is None else parent.index(self.element(f"{path}/{after}")) + 1
        parent.insert(position, new)
        return self

    def violations(self, rule: Rule) -> list[Violation]:
        return list(validate_srb(self.tree, rules=(rule,)))


@pytest.fixture
def case(synthetic_dir: Path) -> Case:
    """The synthetic SRB invoice, ready to edit."""
    return Case(synthetic_dir / "srb-minimal-invoice.xml")


@pytest.fixture
def credit_note(synthetic_dir: Path) -> Case:
    """The synthetic credit note, ready to edit."""
    return Case(synthetic_dir / "credit-note-full.xml")
