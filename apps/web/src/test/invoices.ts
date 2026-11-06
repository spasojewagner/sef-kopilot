import type { Invoice, StoredInvoice } from "@/lib/invoices";

/** An invoice as the API lists it, with ``changes`` of the test's own. */
export function invoice(changes: Partial<Invoice> = {}): Invoice {
  return {
    id: "0b3f6a2e-1c4d-4e5f-8a9b-0c1d2e3f4a5b",
    submitted_by: "u-alice",
    submitted_at: "2026-11-06T09:15:00Z",
    validated_at: "2026-11-06T09:15:01Z",
    profile: "srb",
    valid: false,
    size: 4096,
    sha256: "a".repeat(64),
    summary: {
      document_type: "Invoice",
      number: "F-2026-0042",
      issue_date: "2026-11-05",
      currency: "RSD",
      seller: "Primer d.o.o.",
      buyer: "Kupac a.d.",
      payable_amount: "120000.00",
    },
    ...changes,
  };
}

/** A stored invoice with a report of one fatal violation and one warning. */
export function storedInvoice(
  changes: Partial<StoredInvoice> = {},
): StoredInvoice {
  return {
    ...invoice(),
    report: {
      profile: "srb",
      valid: false,
      violations: [
        {
          rule_id: "SRB-009",
          severity: "fatal",
          message:
            "The seller's PIB must have nine digits with a valid check digit.",
          xpath:
            "/ubl:Invoice/cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID",
          layer: "srb-cius",
          code: null,
          line: 31,
        },
        {
          rule_id: "BR-CO-15",
          severity: "warning",
          message: "Invoice total amount with VAT = total without VAT + VAT.",
          xpath: "/ubl:Invoice/cac:LegalMonetaryTotal",
          layer: "arithmetic",
          code: null,
          line: null,
        },
      ],
      set_aside: [],
      layers: [
        { layer: "xml", ran: true, violations: 0, note: null },
        { layer: "xsd", ran: true, violations: 0, note: null },
        {
          layer: "schematron",
          ran: true,
          violations: 0,
          note: "EN 16931 UBL 1.3.16",
        },
        { layer: "srb-cius", ran: true, violations: 1, note: null },
        { layer: "arithmetic", ran: true, violations: 1, note: null },
      ],
      omitted: 0,
      set_aside_omitted: 0,
    },
    ...changes,
  };
}
