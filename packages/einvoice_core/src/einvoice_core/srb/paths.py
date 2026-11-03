"""UBL paths that several SRB-CIUS rules share, relative to the document element.

Invoices and credit notes place the parties at the same paths, so one set serves both.
"""

from __future__ import annotations

from typing import Final

__all__ = ["BUYER", "PAYEE", "SELLER", "TAX_REPRESENTATIVE", "VAT_IDENTIFIER"]

#: The seller (BG-4).
SELLER: Final = "cac:AccountingSupplierParty/cac:Party"
#: The buyer (BG-7).
BUYER: Final = "cac:AccountingCustomerParty/cac:Party"
#: The payee (BG-10).
PAYEE: Final = "cac:PayeeParty"
#: The seller's tax representative (BG-11).
TAX_REPRESENTATIVE: Final = "cac:TaxRepresentativeParty"
#: A party's VAT identifier (BT-31, BT-48, BT-63): its tax registration under the scheme VAT.
VAT_IDENTIFIER: Final = (
    "cac:PartyTaxScheme[normalize-space(cac:TaxScheme/cbc:ID) = 'VAT']/cbc:CompanyID"
)
