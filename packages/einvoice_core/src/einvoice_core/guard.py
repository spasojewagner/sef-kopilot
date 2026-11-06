"""What no patch may change: the fields a person decides (ADR-0023, the brief's guardrails).

A repair may fix how an invoice says something, never what it says about money, tax, the
parties or when. A patch that touches one of these is not applied; it is shown to a person as
needing their decision:

- an amount, or what an amount is computed from: every ``*Amount`` and ``*Quantity``, the
  allowance or charge indicator and multiplier, every currency (``*CurrencyCode``,
  ``currencyID``) and exchange rate; the totals (``cac:LegalMonetaryTotal``);
- the VAT: the categories and rates (``cac:TaxCategory``, ``cac:ClassifiedTaxCategory``),
  exemption reasons, and the VAT totals (``cac:TaxTotal``);
- the tax identifiers: a party's ``cac:PartyTaxScheme`` (the PIB) and its electronic address
  (``cbc:EndpointID``, which in SEF is the PIB);
- the company identifiers: ``cac:PartyLegalEntity`` (the registration number and name) and
  ``cac:PartyIdentification``; the payee's account (``cac:PayeeFinancialAccount``);
- the dates and times: every ``*Date`` and ``*Time``, and the invoicing periods
  (``cac:InvoicePeriod``, which also says when VAT is due);
- the document's own number (``cbc:ID`` of the invoice or credit note).

A patch touches what it changes, what it is inside of, and, when it removes an element, what
that element holds. UBL names a basic component by what it represents (``Amount``,
``Quantity``, ``Date``…), so a suffix protects every element of its kind, the ones no invoice
here uses yet included.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Final

from lxml import etree

from einvoice_core.xml import CAC, CBC, CN, UBL

__all__ = ["AMOUNT", "COMPANY_IDENTIFIER", "DATE", "NUMBER", "TAX_IDENTIFIER", "VAT", "protection"]

AMOUNT: Final = "an amount, or what one is computed from"
VAT: Final = "a VAT category, rate or total"
TAX_IDENTIFIER: Final = "a tax identifier"
COMPANY_IDENTIFIER: Final = "a company identifier or account"
DATE: Final = "a date or a time"
NUMBER: Final = "the document's number"

_AGGREGATES: Final = {
    f"{{{CAC}}}LegalMonetaryTotal": AMOUNT,
    f"{{{CAC}}}TaxTotal": VAT,
    f"{{{CAC}}}TaxCategory": VAT,
    f"{{{CAC}}}ClassifiedTaxCategory": VAT,
    f"{{{CAC}}}PartyTaxScheme": TAX_IDENTIFIER,
    f"{{{CAC}}}PartyLegalEntity": COMPANY_IDENTIFIER,
    f"{{{CAC}}}PartyIdentification": COMPANY_IDENTIFIER,
    f"{{{CAC}}}PayeeFinancialAccount": COMPANY_IDENTIFIER,
    f"{{{CAC}}}InvoicePeriod": DATE,
    f"{{{CAC}}}TaxExchangeRate": AMOUNT,
    f"{{{CAC}}}PricingExchangeRate": AMOUNT,
    f"{{{CAC}}}PaymentExchangeRate": AMOUNT,
    f"{{{CAC}}}PaymentAlternativeExchangeRate": AMOUNT,
}
_BASIC: Final = {
    f"{{{CBC}}}ChargeIndicator": AMOUNT,
    f"{{{CBC}}}MultiplierFactorNumeric": AMOUNT,
    f"{{{CBC}}}TaxExemptionReasonCode": VAT,
    f"{{{CBC}}}TaxExemptionReason": VAT,
    f"{{{CBC}}}EndpointID": TAX_IDENTIFIER,
}
_SUFFIXES: Final = (
    ("Amount", AMOUNT),
    ("Quantity", AMOUNT),
    ("CurrencyCode", AMOUNT),
    ("Date", DATE),
    ("Time", DATE),
)
_ROOTS: Final = {f"{{{UBL}}}Invoice", f"{{{CN}}}CreditNote"}
_DOCUMENT_NUMBER: Final = f"{{{CBC}}}ID"


def _of(tag: str) -> str | None:
    if (found := _AGGREGATES.get(tag) or _BASIC.get(tag)) is not None:
        return found
    if tag.startswith(f"{{{CBC}}}"):
        local = etree.QName(tag).localname
        return next((what for suffix, what in _SUFFIXES if local.endswith(suffix)), None)
    return None


def _named(tags: Sequence[str], attribute: str | None) -> tuple[str, str] | None:
    for depth, tag in enumerate(tags):
        if (what := _of(tag)) is not None:
            return what, tag
        if depth == 1 and tags[0] in _ROOTS and tag == _DOCUMENT_NUMBER:
            return NUMBER, tag
    if attribute == "currencyID":
        return AMOUNT, f"@{attribute}"
    return None


def protection(
    tags: Sequence[str], attribute: str | None = None, holds: Iterable[str] = ()
) -> str | None:
    """Why a patch may not change the place whose elements, from the root, are ``tags`` (in
    Clark notation), with ``attribute`` if the place is one and ``holds`` the names of what an
    element removed there contains; ``None`` when nothing there is protected."""
    named = _named(tags, attribute)
    if named is None:
        inside = next((tag for tag in holds if _of(tag) is not None), None)
        named = (str(_of(inside)), inside) if inside is not None else None
    if named is None:
        return None
    what, where = named
    return f"it touches {what} ({_written(where)}): a person decides it"


def _written(tag: str) -> str:
    if tag.startswith("@"):
        return tag
    qname = etree.QName(tag)
    prefix = {CAC: "cac", CBC: "cbc"}.get(qname.namespace or "", "")
    return f"{prefix}:{qname.localname}" if prefix else qname.localname
