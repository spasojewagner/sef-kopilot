"""Where UBL 2.1 puts each element among its siblings, read from its schemas (ADR-0023).

Every UBL aggregate is an ``xsd:sequence``: its children must come in one order, and a patch
that adds an element must put it where the schema says, or the schema refuses the document.
The order is read once from the schemas the validator already fetched (``ubl-2.1``): the
document types (``Invoice``, ``CreditNote``) and the common aggregate components, each an
element declared with a type whose sequence names its children by reference. Basic components
have no children; the extensions are not read, as no patch may name them.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import Final

from lxml import etree

from einvoice_core.rulesets import ruleset_path
from einvoice_core.xml import load_document
from einvoice_core.xsd import UBL_RULESET

__all__ = ["Order", "schema_order"]

_XSD: Final = "http://www.w3.org/2001/XMLSchema"
_SCHEMAS: Final = (
    "xsd/maindoc/UBL-Invoice-2.1.xsd",
    "xsd/maindoc/UBL-CreditNote-2.1.xsd",
    "xsd/common/UBL-CommonAggregateComponents-2.1.xsd",
)
#: An XSD file is far larger than an invoice: the aggregate components are 2.4 MB.
_MAX_SCHEMA_BYTES: Final = 16 * 1024 * 1024

#: For each element that has children, in Clark notation, its children's names in the order
#: the schema requires them.
Order = Mapping[str, tuple[str, ...]]


def _qualified(name: str, element: etree._Element) -> str:
    """``cbc:ID`` as Clark notation, with the prefixes the schema file declares."""
    prefix, _, local = name.rpartition(":")
    return f"{{{element.nsmap[prefix or None]}}}{local}"


def _read(path: Path) -> dict[str, tuple[str, ...]]:
    schema = load_document(path, max_bytes=_MAX_SCHEMA_BYTES).getroot()
    namespace = schema.get("targetNamespace")
    sequences = {
        complex_type.get("name"): tuple(
            _qualified(child.get("ref", ""), child)
            for child in complex_type.iterfind(f"{{{_XSD}}}sequence/{{{_XSD}}}element")
        )
        for complex_type in schema.iterfind(f"{{{_XSD}}}complexType")
    }
    return {
        f"{{{namespace}}}{element.get('name')}": sequences[type_name]
        for element in schema.iterfind(f"{{{_XSD}}}element")
        if (type_name := element.get("type")) in sequences
    }


@cache
def _order(root: Path) -> Order:
    order: dict[str, tuple[str, ...]] = {}
    for schema in _SCHEMAS:
        order.update(_read(root / schema))
    return order


def schema_order(*, root: Path | None = None) -> Order:
    """The order of every UBL element's children, read from the fetched UBL 2.1 schemas (or
    those under ``root``) once per process. :class:`~einvoice_core.rulesets.RulesetNotFoundError`
    when they have not been fetched."""
    return _order(root if root is not None else ruleset_path(UBL_RULESET))
