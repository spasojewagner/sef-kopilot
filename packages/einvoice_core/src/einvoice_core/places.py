"""Places in an invoice, named by the canonical paths the validator reports (ADR-0023).

A patch says where it applies with the path a violation gives:
``/ubl:Invoice/cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme[1]/cbc:CompanyID``, or
an attribute of an element, ``…/cbc:EndpointID/@schemeID``. The path is not evaluated as XPath:
it is parsed against a grammar of child steps (an aggregate or a basic component, with a
position where an element has same-named siblings) and walked one step at a time. Nothing else
of XPath is accepted: no functions, axes, wildcards or conditions, so a path selects one place
or none, and costs as many steps as it has. The extensions (``ext:``) are not places a patch may
name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from lxml import etree

from einvoice_core.xml import CAC, CBC, CN, UBL

__all__ = ["MAX_PATH", "Place", "PlaceError", "Step", "find", "place_of", "reach"]

#: Longer than any path the validator reports for a real invoice.
MAX_PATH: Final = 1000

_NAMESPACES: Final = {"ubl": UBL, "cn": CN, "cac": CAC, "cbc": CBC}
_PATH: Final = re.compile(
    r"/(?P<root>ubl:Invoice|cn:CreditNote)"
    r"(?P<steps>(?:/(?:cac|cbc):[A-Za-z][A-Za-z0-9]*(?:\[[1-9][0-9]{0,5}\])?)*)"
    r"(?:/@(?P<attribute>[A-Za-z][A-Za-z0-9]*))?"
)
_STEP: Final = re.compile(r"(?P<prefix>cac|cbc):(?P<name>[A-Za-z][A-Za-z0-9]*)(?:\[(?P<at>\d+)\])?")


class PlaceError(ValueError):
    """A path that names no place: malformed, missing, or naming several elements."""


@dataclass(frozen=True)
class Step:
    """One step of a path: an element's name in Clark notation, and its position among its
    same-named siblings when the path gives one."""

    tag: str
    position: int | None

    @property
    def written(self) -> str:
        """The step as the path writes it."""
        qname = etree.QName(self.tag)
        prefix = "cac" if qname.namespace == CAC else "cbc"
        position = f"[{self.position}]" if self.position is not None else ""
        return f"{prefix}:{qname.localname}{position}"


@dataclass(frozen=True)
class Place:
    """A place in an invoice: the document's root, the steps below it to an element, and an
    attribute of that element, if the place is one."""

    root: str
    steps: tuple[Step, ...]
    attribute: str | None

    @property
    def path(self) -> str:
        """The canonical path of the place."""
        root = "ubl:Invoice" if self.root == f"{{{UBL}}}Invoice" else "cn:CreditNote"
        steps = "".join(f"/{step.written}" for step in self.steps)
        attribute = f"/@{self.attribute}" if self.attribute is not None else ""
        return f"/{root}{steps}{attribute}"

    @property
    def parent(self) -> Place:
        """The place of the element that holds this one: for an attribute, its element."""
        if self.attribute is not None:
            return Place(self.root, self.steps, None)
        if not self.steps:
            raise PlaceError("the document's root has no parent")
        return Place(self.root, self.steps[:-1], None)


def place_of(path: str) -> Place:
    """The place ``path`` names, or :class:`PlaceError` for a path outside the grammar."""
    if len(path) > MAX_PATH:
        raise PlaceError(f"the path is longer than {MAX_PATH} characters")
    match = _PATH.fullmatch(path)
    if match is None and "/ext:" in path:
        raise PlaceError("the extensions (ext:) are not places a patch may name")
    if match is None:
        raise PlaceError(
            "the path is not a canonical path of an invoice: "
            "/ubl:Invoice or /cn:CreditNote, then cac: and cbc: steps, then @attribute if any"
        )
    root_prefix, root_name = match["root"].split(":")
    steps = tuple(
        Step(
            f"{{{_NAMESPACES[step['prefix']]}}}{step['name']}",
            int(step["at"]) if step["at"] is not None else None,
        )
        for step in _STEP.finditer(match["steps"])
    )
    return Place(f"{{{_NAMESPACES[root_prefix]}}}{root_name}", steps, match["attribute"])


def _child(parent: etree._Element, step: Step, path: str) -> etree._Element | None:
    same = [child for child in parent if child.tag == step.tag]
    if step.position is None:
        if len(same) > 1:
            raise PlaceError(
                f"{path} names {len(same)} elements {step.written}: give the position of one"
            )
        return same[0] if same else None
    return same[step.position - 1] if step.position <= len(same) else None


def reach(tree: etree._ElementTree, place: Place) -> tuple[etree._Element, int]:
    """How far the document goes along the path of ``place``: the last element it has on the
    way, and the number of steps to it (all of them when the element is there).
    :class:`PlaceError` when the document is of another type, or a step without a position
    matches several elements."""
    current = tree.getroot()
    if current.tag != place.root:
        raise PlaceError(f"the document is not the {place.path.split('/')[1]} the path names")
    for depth, step in enumerate(place.steps):
        found = _child(current, step, Place(place.root, place.steps[: depth + 1], None).path)
        if found is None:
            return current, depth
        current = found
    return current, len(place.steps)


def find(tree: etree._ElementTree, place: Place) -> etree._Element | None:
    """The element at ``place`` (for an attribute, the element that has it), or ``None`` when
    the document has none there. :class:`PlaceError` as for :func:`reach`."""
    element, depth = reach(tree, place)
    return element if depth == len(place.steps) else None
