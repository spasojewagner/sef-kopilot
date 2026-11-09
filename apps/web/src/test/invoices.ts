import type { Explained } from "@/lib/explanations";
import type { Invoice, StoredInvoice } from "@/lib/invoices";
import type { ListedRepair } from "@/lib/repairs";
import type { Submission } from "@/lib/sef";
import { type Asked, json, stubApi } from "@/test/api";

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

/**
 * The explanations of {@link storedInvoice}'s report, as the API writes them: the fatal rule
 * explained with a passage of the PIB rulebook and one of SRB-CIUS, as the corpus has them,
 * and the warning without citations.
 */
export function explained(changes: Partial<Explained> = {}): Explained {
  const stored = storedInvoice();
  return {
    report: stored.report,
    day: "2026-11-05",
    language: "sr",
    model: "test/quoting",
    explanations: [
      {
        rule_id: "SRB-009",
        violations: 1,
        text: "PIB prodavca mora imati devet cifara i ispravnu kontrolnu cifru.",
        fix: "Upišite PIB prodavca iz rešenja o registraciji.",
        citations: [
          {
            id: "pib-rulebook/article-2/2018-10-01",
            document: "pib-rulebook",
            title: "Pravilnik o poreskom identifikacionom broju",
            label: "Члан 2.",
            heading: "Поступак, начин и рокови одређивања и додељивања ПИБ-а",
            version:
              "Službeni glasnik RS, br. 57/2003, 68/2003, 32/2009, 48/2010 i 44/2018",
            valid_from: "2018-10-01",
            valid_to: null,
            source_url:
              "https://pravno-informacioni-sistem.rs/eli/rep/sgrs/ministarstva/pravilnik/2003/57/1/reg",
          },
          {
            id: "srb-cius/1-3-table-1-bt-31/2025-06-06",
            document: "srb-cius",
            title:
              "Specifikacija prilagođene primene standarda EN 16931-1 za elektronske fakture u unutrašnjem prometu u Republici Srbiji",
            label: "BT-31",
            heading: "Seller VAT identifier — ПИБ продавца",
            version: "06.06.2025",
            valid_from: "2025-06-06",
            valid_to: null,
            source_url:
              "https://www.efaktura.gov.rs/tekst/en/5370/updated-specification-for-the-adapted-implementation-of-the-en-16931-1-standard-for-electronic-invoices-in-domestic-trade-in-the-republic-of-serbia.php",
          },
        ],
        problem: null,
      },
      {
        rule_id: "BR-CO-15",
        violations: 1,
        text: "Ukupan iznos sa PDV-om je zbir iznosa bez PDV-a i PDV-a.",
        fix: null,
        citations: [],
        problem: null,
      },
    ],
    unexplained: [],
    written_at: "2026-11-07T12:00:00Z",
    ...changes,
  };
}

/**
 * An API as an invoice's report finds it: the stored invoice ``stored``, its ``repairs`` and its
 * ``submissions`` to SEF, and ``other`` for anything else; what it was asked is returned.
 */
export function stubReportApi({
  stored = storedInvoice(),
  repairs = [],
  submissions = [],
  other = () => json(404, { detail: "not found" }),
}: {
  stored?: StoredInvoice;
  repairs?: ListedRepair[];
  submissions?: Submission[];
  other?: (asked: Asked) => Response | Promise<Response>;
} = {}): Asked[] {
  return stubApi((asked) => {
    if (asked.path === `/invoices/${stored.id}`) {
      return json(200, stored);
    }
    if (asked.path === `/invoices/${stored.id}/repairs`) {
      return json(200, repairs);
    }
    if (asked.path === `/invoices/${stored.id}/sef` && asked.method === "GET") {
      return json(200, submissions);
    }
    return other(asked);
  });
}
