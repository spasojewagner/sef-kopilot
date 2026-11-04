"""VAT categories, rates and exemption reason codes of SRB-CIUS (BT-118 to BT-121).

SRB-CIUS (1.3, Table 1, BT-118) lists the VAT category codes SEF accepts and says that a VAT
category is the code together with the rate: S at 20 % or 10 % (S20, S10) and AE, reverse
charge with the recipient owing the VAT, at 20 % or 10 % (AE20, AE10); the other codes have no
rate of their own. The Ministry of Finance lists per category the codes that state why VAT is
not charged, or is owed by the recipient ("Poreske kategorije i šifre od 1. septembra 2024.",
source ``tax-categories``); they go into the VAT exemption reason code (BT-121).
:data:`EXEMPTION_CODES` is transcribed from that document (SHA-256 ``28a51342…6033``) with its
keys as it writes them; the document spells AE in Cyrillic letters, the codes themselves are
Latin. For S, the list has only ``PDV-RS-OBJ``, the first transfer of newly built buildings.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from lxml import etree

from einvoice_core.srb.rule import Document

__all__ = [
    "CATEGORIES",
    "CODE_REQUIRED",
    "EXEMPTION_CODES",
    "RATED",
    "RATES",
    "TaxCategory",
    "breakdown_categories",
    "list_key",
    "rate",
    "tax_categories",
]

#: BT-118 (and BT-95, BT-102, BT-151): the codes SRB-CIUS allows, with what they mean.
CATEGORIES: Final[dict[str, str]] = {
    "S": "standard rate",
    "Z": "exempt with the right to deduct input VAT",
    "E": "exempt without the right to deduct input VAT",
    "AE": "reverse charge, the recipient owes the VAT",
    "R": "excluded from VAT",
    "O": "not subject to VAT",
    "OE": "not subject to VAT, second list",
    "SS": "special taxation procedure",
    "N": "annulment",
}
#: The categories that carry a rate, and the rates SRB-CIUS names for them.
RATED: Final = frozenset({"S", "AE"})
RATES: Final = (Decimal("20"), Decimal("10"))
#: The categories whose entry in the Ministry's list says to choose one of its codes.
CODE_REQUIRED: Final = frozenset({"Z", "E", "R", "O", "OE", "SS", "N"})

#: The Ministry's list: category (with the rate for S and AE) → the codes for BT-121.
EXEMPTION_CODES: Final[dict[str, tuple[str, ...]]] = {
    "S20": ("PDV-RS-OBJ",),
    "S10": ("PDV-RS-OBJ",),
    "AE20": (
        "PDV-RS-10-2-1",
        "PDV-RS-10-2-2",
        "PDV-RS-10-2-3",
        "PDV-RS-10-2-4",
        "PDV-RS-10-2-5-1",
        "PDV-RS-10-2-5-2",
        "PDV-RS-10-2-5-3",
        "PDV-RS-10-2-5-3-OBJ",
        "PDV-RS-36b-6",
    ),
    "AE10": (
        "PDV-RS-10-2-1",
        "PDV-RS-10-2-2",
        "PDV-RS-10-2-3",
        "PDV-RS-10-2-4",
        "PDV-RS-10-2-5-1",
        "PDV-RS-10-2-5-2",
        "PDV-RS-10-2-5-3",
        "PDV-RS-10-2-5-3-OBJ",
    ),
    "Z": (
        "PDV-RS-24-1-1",
        "PDV-RS-24-1-2",
        "PDV-RS-24-1-3",
        "PDV-RS-24-1-5",
        "PDV-RS-24-1-5a",
        "PDV-RS-24-1-6",
        "PDV-RS-24-1-6a",
        "PDV-RS-24-1-7",
        "PDV-RS-24-1-7a",
        "PDV-RS-24-1-8",
        "PDV-RS-24-1-9",
        "PDV-RS-24-1-10",
        "PDV-RS-24-1-11",
        "PDV-RS-24-1-12",
        "PDV-RS-24-1-13",
        "PDV-RS-24-1-14",
        "PDV-RS-24-1-15",
        "PDV-RS-24-1-16-1",
        "PDV-RS-24-1-16-2",
        "PDV-RS-24-1-16-3",
        "PDV-RS-24-1-16-4",
        "PDV-RS-24-1-16a",
        "PDV-RS-24-1-16b",
        "PDV-RS-24-1-16v",
        "PDV-RS-24-1-16g",
        "PDV-RS-24-1-17",
    ),
    "E": (
        "PDV-RS-25-1-1",
        "PDV-RS-25-1-1a",
        "PDV-RS-25-1-2",
        "PDV-RS-25-1-3",
        "PDV-RS-25-1-4",
        "PDV-RS-25-1-5",
        "PDV-RS-25-1-6",
        "PDV-RS-25-1-7",
        "PDV-RS-25-1-8",
        "PDV-RS-25-2-1",
        "PDV-RS-25-2-2",
        "PDV-RS-25-2-3",
        "PDV-RS-25-2-3a",
        "PDV-RS-25-2-3b",
        "PDV-RS-25-2-5",
        "PDV-RS-25-2-6",
        "PDV-RS-25-2-7",
        "PDV-RS-25-2-8",
        "PDV-RS-25-2-9",
        "PDV-RS-25-2-10",
        "PDV-RS-25-2-11",
        "PDV-RS-25-2-12",
        "PDV-RS-25-2-13",
        "PDV-RS-25-2-14",
        "PDV-RS-25-2-15",
        "PDV-RS-25-2-16",
        "PDV-RS-25-2-17",
        "PDV-RS-25-2-18",
        "PDV-RS-25-2-19",
    ),
    "R": (
        "PDV-RS-6-1-1",
        "PDV-RS-6a",
        "PDV-RS-6-ostalo",
    ),
    "O": (
        "PDV-RS-11-1-1",
        "PDV-RS-11-1-2",
        "PDV-RS-11-1-3",
        "PDV-RS-11-1-4",
        "PDV-RS-11-1-5",
        "PDV-RS-11-3",
        "PDV-RS-12-4",
        "PDV-RS-12-6-1",
        "PDV-RS-12-6-2",
        "PDV-RS-12-6-3",
        "PDV-RS-12-6-4-1",
        "PDV-RS-12-6-4-2",
        "PDV-RS-12-6-4-3",
        "PDV-RS-12-6-4-4",
        "PDV-RS-12-6-4-5",
        "PDV-RS-12-6-5",
        "PDV-RS-12-6-6",
        "PDV-RS-12-6-7-1",
        "PDV-RS-12-6-7-2",
        "PDV-RS-12-6-7-3",
        "PDV-RS-12-6-7-4",
        "PDV-RS-12-6-7-5",
        "PDV-RS-12-6-7-6",
        "PDV-RS-12-6-7-7",
        "PDV-RS-12-6-7-8",
        "PDV-RS-12-6-7-9",
        "PDV-RS-12-6-7-10",
        "PDV-RS-12-6-7-11",
        "PDV-RS-12-6-7-12",
        "PDV-RS-12-6-8",
        "PDV-RS-12-9",
        "PDV-RS-61",
    ),
    "OE": (
        "PDV-RS-7a-4",
        "PDV-RS-9",
        "PDV-RS-17-4-2",
        "PDV-RS-17-4-3",
        "PDV-RS-4-4-2NP",
        "PDV-RS-5-4-2NP",
        "PDV-RS-3NP-ostalo",
    ),
    "SS": (
        "PDV-RS-33",
        "PDV-RS-35-7",
        "PDV-RS-36-5",
        "PDV-RS-36b-4",
    ),
    "N": (
        "PDV-RS-4",
        "PDV-RS-5",
        "PDV-RS-6-1-1 (BN)",
        "PDV-RS-3-DZ",
    ),
}


def list_key(category: str, percent: Decimal | None) -> str | None:
    """The key of the Ministry's list for a category and its rate (``S20``, ``AE10``, ``Z``).

    ``None`` for a code SRB-CIUS does not allow, or a rated category at another rate.
    """
    if category not in CATEGORIES:
        return None
    if category not in RATED:
        return category
    if percent not in RATES:
        return None
    return f"{category}{int(percent)}"


def rate(document: Document, category: etree._Element) -> Decimal | None:
    """The rate of a ``TaxCategory`` (``cbc:Percent``, an ``xs:decimal``), ``None`` if absent."""
    text = document.text("cbc:Percent", category)
    return None if text is None else Decimal(text)


@dataclass(frozen=True)
class TaxCategory:
    """A ``TaxCategory`` element, where it is, and the business terms of its code and rate."""

    element: etree._Element
    where: str
    """Where it is: VAT breakdown, document level allowance or charge, invoice line."""
    code_term: str
    rate_term: str


def breakdown_categories(document: Document) -> Iterator[TaxCategory]:
    """The categories of the VAT breakdown (BG-23), in the invoice currency only.

    A foreign-currency invoice repeats the breakdown in RSD (SRB-CIUS 1.4) in a second
    ``TaxTotal``; that copy carries only what the RSD amounts need.
    """
    currency = document.text("cbc:DocumentCurrencyCode")
    for total in document.find_all("cac:TaxTotal"):
        amount = document.find("cbc:TaxAmount", total)
        if currency is not None and amount is not None and amount.get("currencyID") != currency:
            continue
        for element in document.find_all("cac:TaxSubtotal/cac:TaxCategory", total):
            yield TaxCategory(element, "VAT breakdown", "BT-118", "BT-119")


def tax_categories(document: Document) -> Iterator[TaxCategory]:
    """Every VAT category the document states: breakdowns, allowances, charges, lines."""
    for element in document.find_all("cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory"):
        yield TaxCategory(element, "VAT breakdown", "BT-118", "BT-119")
    for allowance_charge in document.find_all("cac:AllowanceCharge"):
        charge = document.text("cbc:ChargeIndicator", allowance_charge) in ("true", "1")
        for element in document.find_all("cac:TaxCategory", allowance_charge):
            if charge:
                yield TaxCategory(element, "document level charge", "BT-102", "BT-103")
            else:
                yield TaxCategory(element, "document level allowance", "BT-95", "BT-96")
    lines = (
        "cac:InvoiceLine/cac:Item/cac:ClassifiedTaxCategory"
        " | cac:CreditNoteLine/cac:Item/cac:ClassifiedTaxCategory"
    )
    for element in document.find_all(lines):
        yield TaxCategory(element, "invoice line", "BT-151", "BT-152")
