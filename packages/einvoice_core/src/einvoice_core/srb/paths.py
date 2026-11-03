"""UBL paths that several SRB-CIUS rules share, relative to the document element.

Invoices and credit notes place the parties at the same paths, so one set serves both.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "BUYER",
    "COUNTRY_CODE",
    "LEGAL_REGISTRATION",
    "PAYEE",
    "SELLER",
    "SERBIA",
    "TAX_REPRESENTATIVE",
    "VAT_IDENTIFIER",
    "VAT_STATUS",
]

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
#: A party's VAT registration status (BT-32, seller only): the registration filed under the
#: Serbian scheme RS-VAT-STATUS.
VAT_STATUS: Final = (
    "cac:PartyTaxScheme[normalize-space(cac:TaxScheme/cbc:ID) = 'RS-VAT-STATUS']/cbc:CompanyID"
)
#: A party's legal registration identifier (BT-30, BT-47, BT-61).
LEGAL_REGISTRATION: Final = "cac:PartyLegalEntity/cbc:CompanyID"
#: A party's country code (BT-40, BT-55, BT-69).
COUNTRY_CODE: Final = "cac:PostalAddress/cac:Country/cbc:IdentificationCode"
#: The country code SRB-CIUS prescribes for Serbia (BT-40, BT-55, BT-69). Where a usage note
#: applies to residents, a party whose address has this code is treated as resident.
SERBIA: Final = "RS"
