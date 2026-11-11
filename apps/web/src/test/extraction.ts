/** What the API's reading model answers, in the tests. */
import type { Extraction, InvoiceFields } from "@/lib/extraction";

/** The fields of the synthetic minimal invoice, as the API's model would read them. */
export const READ: InvoiceFields = {
  type_code: "380",
  number: "RF-2026-000123",
  issue_date: "2026-10-05",
  due_date: "2026-10-20",
  delivery_date: null,
  currency: "RSD",
  buyer_reference: null,
  seller: {
    name: "Primer Softver d.o.o.",
    tax_id: "100000024",
    company_id: "20000006",
    street: "Ulica Primera 1",
    city: "Čačak",
    postal_code: "32000",
    country: "RS",
    email: null,
  },
  seller_in_vat_register: true,
  buyer: {
    name: "Ogledni Kupac d.o.o.",
    tax_id: null,
    company_id: null,
    street: null,
    city: "Beograd",
    postal_code: null,
    country: "RS",
    email: null,
  },
  lines: [
    {
      name: "Konsultantski sat",
      quantity: "8",
      unit: "HUR",
      unit_price: "1500.00",
      net_amount: "12000.00",
      vat_category: "S",
      vat_rate: "20",
    },
  ],
  vat_breakdown: [
    {
      vat_category: "S",
      vat_rate: "20",
      taxable_amount: "12000.00",
      tax_amount: "2400.00",
    },
  ],
  totals: {
    line_total: "12000.00",
    tax_exclusive: "12000.00",
    tax: "2400.00",
    tax_inclusive: "14400.00",
    prepaid: null,
    payable: "14400.00",
  },
  payment: {
    account: "160-0000000123456-78",
    model: "97",
    reference: "12-345678-00123",
  },
};

/** The API's answer to a reading of ``fields``, from a picture unless it says. */
export function extraction(
  fields: InvoiceFields = READ,
  document: Extraction["document"] = { kind: "picture", pages: 1, text: false },
): Extraction {
  return { fields, document, model: "groq/qwen/qwen3.8-27b" };
}
