"""Values that SRB-CIUS prescribes, each with the passage it comes from.

Kept apart from the rules so that a reader can check them against the specification in one
place, and so that the explainer and the repairer can offer the permitted values.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "INVOICE_TYPE_CODES",
    "SPECIFICATION_IDENTIFIER",
    "SPECIFICATION_IDENTIFIERS",
    "SPECIFICATION_IDENTIFIER_EXTENDED",
]

#: BT-24 without the Serbian extension (SRB-CIUS 1.2).
SPECIFICATION_IDENTIFIER: Final = "urn:cen.eu:en16931:2017#compliant#urn:mfin.gov.rs:srbdt:2022"
#: BT-24 when the Serbian extension may be used (SRB-CIUS 1.2); valid without extension elements.
SPECIFICATION_IDENTIFIER_EXTENDED: Final = (
    f"{SPECIFICATION_IDENTIFIER}#conformant#urn:mfin.gov.rs:srbdtext:2022"
)
SPECIFICATION_IDENTIFIERS: Final = (SPECIFICATION_IDENTIFIER, SPECIFICATION_IDENTIFIER_EXTENDED)

#: BT-3 (SRB-CIUS 1.3, Table 1): commercial invoice, credit note, debit note, advance invoice.
INVOICE_TYPE_CODES: Final[dict[str, str]] = {
    "380": "commercial invoice",
    "381": "credit note",
    "383": "debit note",
    "386": "advance invoice",
}
