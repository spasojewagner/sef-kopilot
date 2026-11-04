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
from einvoice_core.srb.codes import SPECIFICATION_IDENTIFIER_EXTENDED
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


def vat_total(currency: str, taxable: str, tax: str) -> str:
    """A UBL VAT total with one standard-rated subtotal, as an XML fragment."""
    return (
        f'<cac:TaxTotal><cbc:TaxAmount currencyID="{currency}">{tax}</cbc:TaxAmount>'
        f'<cac:TaxSubtotal><cbc:TaxableAmount currencyID="{currency}">{taxable}</cbc:TaxableAmount>'
        f'<cbc:TaxAmount currencyID="{currency}">{tax}</cbc:TaxAmount>'
        "<cac:TaxCategory><cbc:ID>S</cbc:ID><cbc:Percent>20</cbc:Percent>"
        "<cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:TaxCategory>"
        "</cac:TaxSubtotal></cac:TaxTotal>"
    )


def settle_advance(
    case: Case,
    *,
    currencies: tuple[str, ...] = ("RSD",),
    advance: str = "AV-2026-0007",
    reduced_total: str = "8400.00",
) -> Case:
    """Make the synthetic invoice a final invoice that settles one advance of 6 000 RSD.

    Total with VAT 14 400, paid 6 000 (5 000 + 1 000 VAT), so the reduced total with VAT is
    8 400; the extension gives the advance and the reduced totals in each of ``currencies``.
    """
    advances = "".join(vat_total(currency, "5000.00", "1000.00") for currency in currencies)
    reduced = "".join(vat_total(currency, "7000.00", "1400.00") for currency in currencies)
    case.insert(
        ".",
        "<ext:UBLExtensions><ext:UBLExtension><ext:ExtensionContent><sbt:SrbDtExt>"
        f"<sbt:InvoicedPrepaymentAmount><cbc:ID>{advance}</cbc:ID>{advances}"
        f"</sbt:InvoicedPrepaymentAmount><sbt:ReducedTotals>{reduced}<cac:LegalMonetaryTotal>"
        '<cbc:TaxExclusiveAmount currencyID="RSD">7000.00</cbc:TaxExclusiveAmount>'
        f'<cbc:TaxInclusiveAmount currencyID="RSD">{reduced_total}</cbc:TaxInclusiveAmount>'
        '<cbc:PayableAmount currencyID="RSD">8400.00</cbc:PayableAmount>'
        "</cac:LegalMonetaryTotal></sbt:ReducedTotals>"
        "</sbt:SrbDtExt></ext:ExtensionContent></ext:UBLExtension></ext:UBLExtensions>",
    )
    case.set_text("cbc:CustomizationID", SPECIFICATION_IDENTIFIER_EXTENDED)
    case.insert(
        ".",
        "<cac:BillingReference><cac:InvoiceDocumentReference><cbc:ID>AV-2026-0007</cbc:ID>"
        "<cbc:IssueDate>2026-09-15</cbc:IssueDate></cac:InvoiceDocumentReference>"
        "</cac:BillingReference>",
        after="cac:InvoicePeriod",
    )
    case.insert(
        "cac:LegalMonetaryTotal",
        '<cbc:PrepaidAmount currencyID="RSD">6000.00</cbc:PrepaidAmount>',
        after="cbc:TaxInclusiveAmount",
    )
    return case.set_text("cac:LegalMonetaryTotal/cbc:PayableAmount", "8400.00")


@pytest.fixture
def final_invoice(case: Case) -> Case:
    """The synthetic SRB invoice as a final invoice that settles one advance."""
    return settle_advance(case)
