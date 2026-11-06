import type { ListedRepair, Repair } from "@/lib/repairs";
import { ALICE } from "@/test/api";
import { storedInvoice } from "@/test/invoices";

/** The diff of a repair of SRB-001's mutation, as the API writes it. */
export const DIFF = `--- before
+++ after
@@ -5,5 +5,5 @@
   <cbc:IssueDate>2026-10-05</cbc:IssueDate>
   <cbc:DueDate>2026-10-20</cbc:DueDate>
-  <cbc:InvoiceTypeCode>393</cbc:InvoiceTypeCode>
+  <cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>
   <cbc:Note>Rok za plaćanje je 15 dana od datuma prometa.</cbc:Note>
   <cbc:DocumentCurrencyCode>RSD</cbc:DocumentCurrencyCode>
`;

/** A repair as the invoice's history lists it: {@link ALICE}'s, waiting for a decision. */
export function listedRepair(
  changes: Partial<ListedRepair> = {},
): ListedRepair {
  return {
    id: "7d1e9f3a-2b4c-4d5e-9f60-718293a4b5c6",
    invoice_id: storedInvoice().id,
    status: "proposed",
    proposed_by: ALICE.user.id,
    proposed_with_key: false,
    model: null,
    proposed_at: "2026-11-06T10:30:00Z",
    decided_by: null,
    decided_at: null,
    changed: true,
    valid: true,
    applied: 1,
    needs_decision: 1,
    failed: 1,
    ...changes,
  };
}

/**
 * A repair with three patches: one applied (the invoice type code), one that needs a person's
 * decision (the seller's PIB), and one that could not apply; the copy they leave is valid. The
 * problems are worded as the validator words them.
 */
export function repair(changes: Partial<Repair> = {}): Repair {
  const valid = { ...storedInvoice().report, valid: true, violations: [] };
  return {
    ...listedRepair(),
    outcomes: [
      {
        patch: {
          xpath: "/ubl:Invoice/cbc:InvoiceTypeCode",
          op: "replace",
          value: "380",
          reason: "SRB-001 dopušta samo 380, 381, 383 i 386.",
        },
        status: "applied",
        problem: null,
        before: "393",
        after: "380",
      },
      {
        patch: {
          xpath:
            "/ubl:Invoice/cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID",
          op: "replace",
          value: "RS100000024",
          reason: "Kontrolna cifra PIB-a prodavca.",
        },
        status: "needs-decision",
        problem:
          "it touches a tax identifier (cac:PartyTaxScheme): a person decides it",
        before: null,
        after: null,
      },
      {
        patch: {
          xpath: "/ubl:Invoice/cbc:Note[2]",
          op: "remove",
          value: null,
          reason: "Druga napomena je suvišna.",
        },
        status: "failed",
        problem: "there is nothing at /ubl:Invoice/cbc:Note[2] to remove",
        before: null,
        after: null,
      },
    ],
    diff: DIFF,
    report: valid,
    ...changes,
  };
}
