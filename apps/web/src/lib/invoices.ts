/**
 * The organization's invoices on the API (ADR-0016): stored with the validator's report on
 * them, listed newest first, read one at a time. Every call is in the visitor's name.
 */
import type { Schemas } from "@/lib/api";
import { authorized } from "@/lib/session";

export type Invoice = Schemas["InvoiceOut"];
export type StoredInvoice = Schemas["StoredInvoiceOut"];
export type InvoicePage = Schemas["InvoiceListPage"];
export type Report = Schemas["ValidationReport"];
export type Violation = Schemas["Violation"];
export type Profile = Invoice["profile"];

/** The profiles an invoice is validated under, the Serbian one first. */
export const PROFILES: readonly Profile[] = ["srb", "en16931", "peppol"];

/** Invoices on a page of the list. */
export const PAGE_SIZES = [25, 50, 100] as const;
export const PAGE_SIZE = PAGE_SIZES[0];

export type InvoiceFilters = {
  q: string;
  valid: "true" | "false" | "";
  type: NonNullable<Invoice["summary"]>["document_type"] | "";
  from: string;
  to: string;
  size: (typeof PAGE_SIZES)[number];
};

/**
 * An upload and its validation may take longer than an ordinary request: the API reads a body
 * for 30 s at most, and an instance on a free tier may first have to wake up.
 */
export const UPLOAD_TIMEOUT_MS = 60_000;

/** The names of pictures, for a browser that gives such a file no media type. */
const PICTURE_NAME = /\.(png|jpe?g|gif|webp|avif|heic|heif|tiff?|bmp)$/i;

/**
 * What a chosen file is when it shows an invoice rather than being one: a picture, such as a
 * photo or a screenshot, or a PDF. The validator checks the XML, so neither is sent to it: one
 * is read into an invoice's fields instead, when it is in a format the API reads
 * (`documentTypeOf`, ADR-0062); null for any other file, which the validator judges. The
 * browser's media type says, or else the file's name.
 */
export function renderingOf(file: File): "picture" | "pdf" | null {
  if (file.type === "application/pdf" || /\.pdf$/i.test(file.name)) {
    return "pdf";
  }
  if (file.type.startsWith("image/") || PICTURE_NAME.test(file.name)) {
    return "picture";
  }
  return null;
}

/** Stores an invoice for the visitor's organization, with the validator's report on it. */
export function storeInvoice(
  document: Blob,
  profile: Profile = "srb",
): Promise<StoredInvoice> {
  return authorized<StoredInvoice>(`/invoices?profile=${profile}`, {
    method: "POST",
    headers: { "Content-Type": "application/xml" },
    body: document,
    timeoutMs: UPLOAD_TIMEOUT_MS,
  });
}

/** The validator's report on a document under ``profile``; nothing is stored. */
export function validateInvoice(
  document: Blob | string,
  profile: Profile = "srb",
): Promise<Report> {
  return authorized<Report>(`/invoices/validate?profile=${profile}`, {
    method: "POST",
    headers: { "Content-Type": "application/xml" },
    body: document,
    timeoutMs: UPLOAD_TIMEOUT_MS,
  });
}

/** A page of the organization's invoices, the newest first; ``after`` continues a list. */
export function listInvoices(
  filters: InvoiceFilters,
  after: string | null,
  signal?: AbortSignal,
): Promise<InvoicePage> {
  const query = new URLSearchParams({ limit: String(filters.size) });
  if (after) query.set("after", after);
  if (filters.q) query.set("q", filters.q);
  if (filters.valid) query.set("valid", filters.valid);
  if (filters.type) query.set("document_type", filters.type);
  if (filters.from) query.set("issued_from", filters.from);
  if (filters.to) query.set("issued_to", filters.to);
  return authorized<InvoicePage>(`/invoices?${query}`, { signal });
}

/** A stored invoice with the validator's latest report on it. */
export function getInvoice(
  id: string,
  signal?: AbortSignal,
): Promise<StoredInvoice> {
  return authorized<StoredInvoice>(`/invoices/${encodeURIComponent(id)}`, {
    signal,
  });
}
