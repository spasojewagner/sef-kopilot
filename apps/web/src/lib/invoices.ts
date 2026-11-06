/**
 * The organization's invoices on the API (ADR-0016), stored with the validator's report on
 * them. Every call is in the visitor's name.
 */
import type { Schemas } from "@/lib/api";
import { authorized } from "@/lib/session";

export type Invoice = Schemas["InvoiceOut"];
export type StoredInvoice = Schemas["StoredInvoiceOut"];
export type InvoicePage = Schemas["InvoicePage"];
export type Report = Schemas["ValidationReport"];
export type Violation = Schemas["Violation"];
export type Profile = Invoice["profile"];

/** A stored invoice with the validator's latest report on it. */
export function getInvoice(
  id: string,
  signal?: AbortSignal,
): Promise<StoredInvoice> {
  return authorized<StoredInvoice>(`/invoices/${encodeURIComponent(id)}`, {
    signal,
  });
}
