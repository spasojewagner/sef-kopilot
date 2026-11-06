"""A repair: patches applied to an invoice, the result validated again, and what changed.

:func:`repair` is the deterministic half of layer 3 (ADR-0023). It reads the invoice as the
validator does, applies the patches in order (:mod:`einvoice_core.patches`), validates the
document they leave under the same profile, and shows what changed as a unified diff of the two
documents, both indented alike so that only the changes differ, however the invoice was
written (on one line, with tabs): the diff's line numbers count lines of those copies, not of
the file. Nothing in it asks a model: the patches come from wherever the caller has them, and
layer 1 alone decides whether the patched invoice is valid.
"""

from __future__ import annotations

import copy
import difflib
from collections.abc import Sequence
from typing import Final

from lxml import etree
from pydantic import BaseModel, ConfigDict

from einvoice_core.patches import Outcome, Patch, apply
from einvoice_core.pipeline import PROFILES, ValidationReport, validate
from einvoice_core.schema_order import Order
from einvoice_core.xml import Source, load_document

__all__ = ["Repaired", "repair"]

_FROZEN: Final = ConfigDict(strict=True, frozen=True, extra="forbid")


class Repaired(BaseModel):
    """What a repair made: the outcome of each patch, whether the document differs from the one
    it was, the document (UTF-8, comments dropped as the validator drops them), the validator's
    report on it, and the difference, empty when there is none."""

    model_config = _FROZEN

    outcomes: tuple[Outcome, ...]
    changed: bool
    document: bytes
    report: ValidationReport
    diff: str


def _lines(tree: etree._ElementTree) -> list[str]:
    """The document indented by two spaces a level, as lines to compare."""
    indented = copy.deepcopy(tree)
    etree.indent(indented, space="  ")
    return etree.tostring(indented, encoding="unicode").splitlines(keepends=True)


def repair(
    source: Source,
    patches: Sequence[Patch],
    profile: str = "srb",
    *,
    order: Order | None = None,
) -> Repaired:
    """Apply ``patches`` to the invoice ``source`` and validate what they leave under
    ``profile``. :class:`~einvoice_core.xml.ParseError` for a document that cannot be read: a
    patch needs a document to apply to."""
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}; choose one of {', '.join(PROFILES)}")
    tree = load_document(source)
    original, before = etree.tostring(tree), _lines(tree)
    outcomes = tuple(apply(tree, patches, order=order))
    document = etree.tostring(tree, xml_declaration=True, encoding="UTF-8")
    diff = "".join(difflib.unified_diff(before, _lines(tree), "before", "after", n=2))
    return Repaired(
        outcomes=outcomes,
        changed=etree.tostring(tree) != original,
        document=document,
        report=validate(document, profile),
        diff=diff,
    )
