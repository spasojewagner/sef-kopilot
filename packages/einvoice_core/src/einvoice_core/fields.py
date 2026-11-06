"""The fields of an invoice around a place: what a repairer is shown of it (ADR-0025).

A field is a basic component (``cbc:``) that holds text and no elements, or an attribute, named
by its canonical path (:mod:`einvoice_core.places`) and shown with its value. A field that only
a person decides (:mod:`einvoice_core.guard`) says what kind of field it is. A patch names a
field by its path, and an element to add by the path of the aggregate it goes in and one more
step.

The fields around a place are those of the aggregate that holds it, or of the place itself when
it is an aggregate: around ``…/cac:PostalAddress/cbc:CityName``, every field of the postal
address; around ``…/cac:Party``, every field of the party. The document's root holds the whole
invoice, so around it, around one of its basic components and around no place at all are the
root's own fields: the invoice's number, dates, codes and currencies. Where the document does
not go as far as a place, the fields are those around the last element it has on the way.
Nothing in the extensions (``ext:``) is a field: no patch may change them.

Around several places, each aggregate is listed once, in the order of the places, and an
aggregate inside another is listed with it; the fields of each come in the order of the
document, at most ``limit`` of them in all. A value longer than :data:`MAX_SHOWN` characters
is cut, and says so.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from typing import Final

from lxml import etree
from pydantic import BaseModel, ConfigDict, Field

from einvoice_core.guard import decided
from einvoice_core.places import PlaceError, place_of, reach
from einvoice_core.xml import CAC, CBC, canonical_xpath, sibling_index

__all__ = ["MAX_SHOWN", "InvoiceField", "fields_around"]

#: The characters of a value that a field shows: more than a code, a name or an identifier
#: needs, less than a long note or an attachment.
MAX_SHOWN: Final = 200


class InvoiceField(BaseModel):
    """A basic component of an invoice that holds text, or an attribute, with its value."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    path: str = Field(description="The canonical path of the element or the attribute.")
    value: str = Field(description=f"Its text or its value, at most {MAX_SHOWN} characters.")
    cut: bool = Field(default=False, description="Whether the value is longer than shown.")
    decided: str | None = Field(
        default=None, description="The kind of field a person decides, when it is one."
    )


def _namespace(element: etree._Element) -> str | None:
    """The namespace of an element; ``None`` for a comment or a processing instruction."""
    return etree.QName(element).namespace if isinstance(element.tag, str) else None


def _scope(tree: etree._ElementTree, path: str | None) -> etree._Element | None:
    """The element whose fields are around the place ``path``: the aggregate that holds it, or
    the place itself when it is an aggregate, as far as the document goes; the root for a place
    on the root's level, or none. None for a path that names no place a patch may name."""
    root = tree.getroot()
    if path is None:
        return root
    try:
        element, _ = reach(tree, place_of(path))
    except PlaceError:
        return None
    if element is root or _namespace(element) != CBC:
        return element
    parent = element.getparent()
    assert parent is not None  # a basic component is never the root
    return parent


def _inside(element: etree._Element, others: Sequence[etree._Element]) -> bool:
    return any(ancestor is other for ancestor in element.iterancestors() for other in others)


def _elements(scope: etree._Element, root: etree._Element) -> Iterator[etree._Element]:
    """The elements whose fields are listed for ``scope``, in the order of the document: for
    the root, its basic components; for an aggregate, itself and every element below it but the
    extensions."""
    if scope is root:
        yield from (child for child in root if _namespace(child) == CBC)
        return
    waiting = [scope]
    while waiting:
        element = waiting.pop()
        yield element
        waiting.extend(reversed([child for child in element if _namespace(child) in (CAC, CBC)]))


def _fields(element: etree._Element) -> Iterator[tuple[str, str, str | None]]:
    """The fields of one element: its attributes, then its text if it is a basic component
    that holds no elements; each as its path, its value and the kind a person decides."""
    path = canonical_xpath(element)
    tags = [str(each.tag) for each in [*reversed(list(element.iterancestors())), element]]
    for name, value in element.attrib.items():
        if not name.startswith("{"):  # an attribute of another namespace has no canonical path
            yield f"{path}/@{name}", value, decided(tags, name)
    if _namespace(element) == CBC and not any(isinstance(child.tag, str) for child in element):
        yield path, element.text or "", decided(tags)


def _field(path: str, value: str, kind: str | None) -> InvoiceField:
    cut = len(value) > MAX_SHOWN
    return InvoiceField(path=path, value=value[:MAX_SHOWN], cut=cut, decided=kind)


def fields_around(
    tree: etree._ElementTree, paths: Iterable[str | None], *, limit: int
) -> tuple[InvoiceField, ...]:
    """The fields of ``tree`` around the places ``paths`` (``None`` for a violation of the
    document as a whole), at most ``limit`` of them."""
    root = tree.getroot()
    scopes: list[etree._Element] = []
    for path in paths:
        scope = _scope(tree, path)
        if scope is not None and not any(scope is other for other in scopes):
            scopes.append(scope)
    aggregates = [scope for scope in scopes if scope is not root]
    listed: list[InvoiceField] = []
    with sibling_index():
        for scope in scopes:
            if scope is not root and _inside(scope, aggregates):
                continue  # listed with the aggregate it is in
            for element in _elements(scope, root):
                for path, value, kind in _fields(element):
                    if len(listed) >= limit:
                        return tuple(listed)
                    listed.append(_field(path, value, kind))
    return tuple(listed)
