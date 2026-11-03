"""The document model is strict, immutable and keyed to EN 16931 business terms."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from einvoice_core import model


def _totals(**overrides: object) -> model.MonetaryTotals:
    fields: dict[str, object] = {
        "xpath": "/ubl:Invoice/cac:LegalMonetaryTotal",
        "payable_amount": Decimal("10.00"),
    }
    fields.update(overrides)
    return model.MonetaryTotals.model_validate(fields)


def _party(name: str) -> model.Party:
    return model.Party(xpath=f"/ubl:Invoice/cac:{name}", name=name)


def _line(position: int, net_amount: str) -> model.InvoiceLine:
    return model.InvoiceLine(
        xpath=f"/ubl:Invoice/cac:InvoiceLine[{position}]",
        position=position,
        id=str(position),
        net_amount=Decimal(net_amount),
        item=model.Item(xpath=f"/ubl:Invoice/cac:InvoiceLine[{position}]/cac:Item"),
    )


def _invoice(**overrides: object) -> model.Invoice:
    fields: dict[str, object] = {
        "xpath": "/ubl:Invoice",
        "document_type": "Invoice",
        "id": "INV-1",
        "issue_date": date(2026, 1, 15),
        "currency": "RSD",
        "seller": _party("AccountingSupplierParty"),
        "buyer": _party("AccountingCustomerParty"),
        "totals": _totals(),
        "lines": (_line(1, "10.00"),),
    }
    fields.update(overrides)
    return model.Invoice.model_validate(fields)


def test_amounts_must_be_decimal_not_float() -> None:
    with pytest.raises(ValidationError, match="payable_amount"):
        _totals(payable_amount=10.0)


def test_sequences_must_be_tuples_in_strict_mode() -> None:
    with pytest.raises(ValidationError, match="lines"):
        _invoice(lines=[_line(1, "1.00")])


def test_models_are_frozen() -> None:
    invoice = _invoice()
    with pytest.raises(ValidationError, match="frozen"):
        invoice.id = "changed"


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        _invoice(colour="blue")


def test_document_type_is_closed() -> None:
    with pytest.raises(ValidationError, match="document_type"):
        _invoice(document_type="Order")


def test_allowances_and_charges_are_split_by_indicator() -> None:
    allowance = model.AllowanceCharge(
        xpath="/ubl:Invoice/cac:AllowanceCharge[1]", is_charge=False, amount=Decimal("5")
    )
    charge = model.AllowanceCharge(
        xpath="/ubl:Invoice/cac:AllowanceCharge[2]", is_charge=True, amount=Decimal("7")
    )
    invoice = _invoice(allowances_charges=(allowance, charge))

    assert invoice.allowances == (allowance,)
    assert invoice.charges == (charge,)


def test_line_allowances_and_charges_are_split_by_indicator() -> None:
    allowance = model.AllowanceCharge(
        xpath="/ubl:Invoice/cac:InvoiceLine/cac:AllowanceCharge[1]",
        is_charge=False,
        amount=Decimal("1"),
    )
    charge = model.AllowanceCharge(
        xpath="/ubl:Invoice/cac:InvoiceLine/cac:AllowanceCharge[2]",
        is_charge=True,
        amount=Decimal("2"),
    )
    line = _line(1, "9.00").model_copy(update={"allowances_charges": (allowance, charge)})

    assert line.allowances == (allowance,)
    assert line.charges == (charge,)


def _tax_total(currency: str | None, amount: str, with_breakdown: bool) -> model.TaxTotal:
    breakdown = (
        (
            model.VatBreakdown(
                xpath="/ubl:Invoice/cac:TaxTotal[1]/cac:TaxSubtotal",
                tax_amount=Decimal(amount),
                category_code="S",
            ),
        )
        if with_breakdown
        else ()
    )
    return model.TaxTotal(
        xpath="/ubl:Invoice/cac:TaxTotal",
        currency=currency,
        tax_amount=Decimal(amount),
        breakdown=breakdown,
    )


def test_vat_breakdown_comes_from_the_document_currency_tax_total() -> None:
    accounting = _tax_total("EUR", "117.20", with_breakdown=False)
    document = _tax_total("RSD", "13724.00", with_breakdown=True)
    invoice = _invoice(currency="RSD", tax_currency="EUR", tax_totals=(accounting, document))

    assert invoice.document_currency_tax_total is document
    assert invoice.vat_breakdown == document.breakdown


def test_tax_total_without_currency_counts_as_document_currency() -> None:
    unmarked = _tax_total(None, "2.00", with_breakdown=True)
    invoice = _invoice(tax_totals=(unmarked,))

    assert invoice.document_currency_tax_total is unmarked


def test_no_matching_tax_total_gives_an_empty_breakdown() -> None:
    foreign_only = _tax_total("EUR", "2.00", with_breakdown=True)
    invoice = _invoice(currency="RSD", tax_totals=(foreign_only,))

    assert invoice.document_currency_tax_total is None
    assert invoice.vat_breakdown == ()
