"""Patches: the changes a repair proposes, applied by code and never by a model (ADR-0023).

A patch is ``{xpath, op, value, reason}``: the canonical path of one place in the invoice
(:mod:`einvoice_core.places`), what to do there, the new text, and why, for the person who
approves it. Three operations:

- ``replace`` the text of an element that holds no elements, or the value of an attribute;
- ``add`` a basic component (``cbc:``) with ``value`` as its text, or an attribute with
  ``value``. The aggregates on the way that are not there are added with it, each where the
  UBL schema puts it among its siblings (:mod:`einvoice_core.schema_order`);
- ``remove`` an element with all it holds, or an attribute. An aggregate left holding nothing
  is removed with it.

No patch leaves an element empty: an empty element says nothing, and Peppol refuses the
document that has one (``PEPPOL-EN16931-R008``). So a value is never blank, an aggregate is
never added on its own, and a removal takes the aggregates it empties with it.

Patches apply in order, each to the document the ones before it left, and each has an outcome:
applied, refused because it touches what a person decides (:mod:`einvoice_core.guard`), or
failed, with the reason. A patch that fails changes nothing.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Final, Literal, Self

from lxml import etree
from pydantic import BaseModel, ConfigDict, Field, model_validator

from einvoice_core.guard import protection
from einvoice_core.places import MAX_PATH, Place, PlaceError, Step, find, place_of, reach
from einvoice_core.schema_order import Order, schema_order
from einvoice_core.xml import CAC, CBC

__all__ = ["MAX_PATCHES", "MAX_VALUE", "Outcome", "Patch", "PatchError", "Status", "apply"]

#: More than any repair of one invoice needs.
MAX_PATCHES: Final = 100
#: The longest text a patch may write, longer than any UBL field's value.
MAX_VALUE: Final = 1000

Operation = Literal["replace", "add", "remove"]
Status = Literal["applied", "needs-decision", "failed"]

#: What XML 1.0 cannot hold (its ``Char`` production): control characters other than tab and
#: the line ends, surrogates, U+FFFE and U+FFFF. lxml refuses them with an exception.
_NOT_XML: Final = re.compile(r"[^\t\n\r\x20-퟿-�\U00010000-\U0010ffff]")
_FROZEN: Final = ConfigDict(strict=True, frozen=True, extra="forbid")


class Patch(BaseModel):
    """One change to one place of an invoice."""

    model_config = _FROZEN

    xpath: str = Field(min_length=1, max_length=MAX_PATH)
    op: Operation
    value: str | None = Field(default=None, max_length=MAX_VALUE)
    reason: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def _value_fits(self) -> Self:
        if self.op == "remove" and self.value is not None:
            raise ValueError("a patch that removes has no value")
        if self.op != "remove" and self.value is None:
            raise ValueError(f"a patch that does {self.op} has a value")
        if self.value is not None and not self.value.strip():
            raise ValueError("the value is blank: a patch that takes a field out removes it")
        for name, text in (("value", self.value), ("reason", self.reason)):
            if text is not None and _NOT_XML.search(text):
                raise ValueError(f"the {name} holds a character XML does not allow")
        return self


class Outcome(BaseModel):
    """What became of a patch. For an applied one, ``before`` is the text or attribute value
    its place had, and ``after`` the one it has now; either is ``None`` where there is none."""

    model_config = _FROZEN

    patch: Patch
    status: Status
    problem: str | None = None
    before: str | None = None
    after: str | None = None


class PatchError(ValueError):
    """Why a patch cannot apply to the document as it is."""


def _tags(place: Place) -> list[str]:
    return [place.root, *(step.tag for step in place.steps)]


def _name(step: Step) -> str:
    return step.written.split("[", 1)[0]


def _replace(tree: etree._ElementTree, place: Place, value: str) -> tuple[str, str]:
    element = find(tree, place)
    if element is None:
        where = place if place.attribute is None else place.parent
        raise PatchError(f"there is no {where.path.rsplit('/', 1)[-1]} at {where.parent.path}")
    if place.attribute is not None:
        before = element.get(place.attribute)
        if before is None:
            raise PatchError(f"{place.parent.path} has no attribute {place.attribute}: add it")
        element.set(place.attribute, value)
        return before, value
    if len(element):
        raise PatchError(f"{place.path} holds elements: replace what it holds, one by one")
    before = element.text or ""
    element.text = value
    return before, value


def _position(parent: etree._Element, tag: str, order: Sequence[str]) -> int:
    """Where among ``parent``'s children an element ``tag`` goes: after its same-named
    siblings, before the first child the schema puts after it."""
    rank = order.index(tag)
    for index, child in enumerate(parent):
        if child.tag == tag:
            continue
        if child.tag in order and order.index(child.tag) > rank:
            return index
    return len(parent)


def _indentation(element: etree._Element) -> str | None:
    """The spaces before ``element`` on its line, or ``None`` when the document is not
    indented there: the whitespace before an element is its previous sibling's tail, or its
    parent's text."""
    parent = element.getparent()
    if parent is None:
        return ""
    previous = element.getprevious()
    space = previous.tail if previous is not None else parent.text
    if space is None or "\n" not in space or space.strip():
        return None
    return space.rsplit("\n", 1)[1]


def _insert(parent: etree._Element, index: int, element: etree._Element) -> None:
    """Insert ``element`` at ``index``, indented as its neighbours are: a child's tail is the
    indentation of what follows it. In an element that holds none yet, the new one is
    indented a level below its parent, a level being what separates the parent from its own
    parent."""
    if len(parent):
        if index == 0:
            element.tail = parent.text
        elif index < len(parent):
            element.tail = parent[index - 1].tail
        else:
            last = parent[-1]
            element.tail, last.tail = last.tail, parent.text
    elif (holder := parent.getparent()) is not None:
        own, above = _indentation(parent), _indentation(holder)
        if own is not None and above is not None and own.startswith(above) and own != above:
            parent.text = f"\n{own}{own[len(above) :]}"
            element.tail = f"\n{own}"
    parent.insert(index, element)


def _new(parent: etree._Element, tag: str) -> etree._Element:
    """A new element for ``parent``. Its namespace is declared with the canonical prefix when
    nothing in scope there declares it, where lxml would otherwise invent a prefix (``ns0``)."""
    prefix, namespace = ("cac", CAC) if tag.startswith(f"{{{CAC}}}") else ("cbc", CBC)
    if namespace in parent.nsmap.values():
        return etree.Element(tag)
    return etree.Element(tag, nsmap={prefix: namespace})


def _add_attribute(tree: etree._ElementTree, place: Place, attribute: str, value: str) -> str:
    element = find(tree, place)
    if element is None:
        raise PatchError(f"there is no {place.parent.path} to add the attribute to: add it first")
    if element.get(attribute) is not None:
        raise PatchError(f"{place.path} is there already: replace it")
    element.set(attribute, value)
    return value


def _add(tree: etree._ElementTree, place: Place, value: str, order: Order) -> str:
    """Add the basic component or attribute at ``place``, with the aggregates on the way that
    are missing. Every step is checked before anything is added, so a patch that fails changes
    nothing."""
    if place.attribute is not None:
        return _add_attribute(tree, place, place.attribute, value)
    if not place.steps or not place.steps[-1].tag.startswith(f"{{{CBC}}}"):
        raise PatchError(
            "an aggregate (cac:) is not added on its own: add a basic component (cbc:) it "
            "holds, and the aggregate comes with it"
        )
    holder, depth = reach(tree, place)
    if depth == len(place.steps):
        raise PatchError(f"{place.path} is there already: replace it")
    parent_tag, missing = str(holder.tag), place.steps[depth:]
    for offset, step in enumerate(missing):
        at = Place(place.root, place.steps[: depth + offset], None).path
        same = sum(1 for child in holder if child.tag == step.tag) if offset == 0 else 0
        if (step.position or 1) != same + 1:
            raise PatchError(
                f"{at} has {same} {_name(step)}: an element is added after the last of its "
                f"name, at position {same + 1}"
            )
        if step.tag not in order.get(parent_tag, ()):
            raise PatchError(f"UBL allows no {_name(step)} in {at}")
        parent_tag = step.tag
    parent = holder
    for step in missing:
        element = _new(parent, step.tag)
        _insert(parent, _position(parent, step.tag, order[str(parent.tag)]), element)
        parent = element
    parent.text = value
    return value


def _remove(element: etree._Element) -> None:
    """Remove ``element``, leaving its neighbours indented as they were, and the aggregate
    that held it when it held nothing else."""
    parent = element.getparent()
    if parent is None:
        raise PatchError("the document's root cannot be removed")
    previous = element.getprevious()
    if previous is not None:
        previous.tail = element.tail
    else:
        parent.text = element.tail
    parent.remove(element)
    if not len(parent) and not (parent.text or "").strip() and not parent.attrib:
        if parent.getparent() is not None:
            _remove(parent)
        else:
            parent.text = None


def _removed(tree: etree._ElementTree, place: Place) -> str | None:
    element = find(tree, place)
    if element is None:
        raise PatchError(f"there is nothing at {place.path} to remove")
    if place.attribute is not None:
        before = element.attrib.pop(place.attribute, None)
        if before is None:
            raise PatchError(f"{place.parent.path} has no attribute {place.attribute}")
        return before
    before = None if len(element) else (element.text or "")
    _remove(element)
    return before


def _held(tree: etree._ElementTree, place: Place) -> list[str]:
    """The names of what the element at ``place`` holds, which removing it would remove."""
    element = find(tree, place) if place.attribute is None else None
    if element is None:
        return []
    return [str(held.tag) for held in element.iterdescendants(etree.Element)]


def _change(
    tree: etree._ElementTree, place: Place, patch: Patch, order: Order
) -> tuple[str | None, str | None]:
    if patch.op == "remove":
        return _removed(tree, place), None
    value = str(patch.value)
    if patch.op == "replace":
        return _replace(tree, place, value)
    return None, _add(tree, place, value, order)


def _apply_one(tree: etree._ElementTree, patch: Patch, order: Order) -> Outcome:
    try:
        place = place_of(patch.xpath)
        holds = _held(tree, place) if patch.op == "remove" else []
        if (refused := protection(_tags(place), place.attribute, holds)) is not None:
            return Outcome(patch=patch, status="needs-decision", problem=refused)
        before, after = _change(tree, place, patch, order)
    except (PlaceError, PatchError) as error:
        return Outcome(patch=patch, status="failed", problem=str(error))
    return Outcome(patch=patch, status="applied", before=before, after=after)


def apply(
    tree: etree._ElementTree, patches: Sequence[Patch], *, order: Order | None = None
) -> list[Outcome]:
    """Apply ``patches`` to ``tree`` in order, changing it, and say what became of each."""
    if len(patches) > MAX_PATCHES:
        raise ValueError(f"at most {MAX_PATCHES} patches apply at once")
    known = order if order is not None else schema_order()
    return [_apply_one(tree, patch, known) for patch in patches]
