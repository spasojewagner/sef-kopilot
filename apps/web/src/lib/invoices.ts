/**
 * The organization's invoices on the API (ADR-0016): stored with the validator's report on
 * them, listed newest first, read one at a time. Every call is in the visitor's name.
 */
import type { Schemas } from "@/lib/api";
import { authorized } from "@/lib/session";

export type Invoice = Schemas["InvoiceOut"];
export type StoredInvoice = Schemas["StoredInvoiceOut"];
export type InvoicePage = Schemas["InvoicePage"];
export type Report = Schemas["ValidationReport"];
export type Violation = Schemas["Violation"];
export type Profile = Invoice["profile"];

/** The profiles an invoice is validated under, the Serbian one first. */
export const PROFILES: readonly Profile[] = ["srb", "en16931", "peppol"];

/** Invoices on a page of the list. */
export const PAGE_SIZE = 20;

/**
 * An upload and its validation may take longer than an ordinary request: the API reads a body
 * for 30 s at most, and an instance on a free tier may first have to wake up.
 */
export const UPLOAD_TIMEOUT_MS = 60_000;

/** The names of pictures, for a browser that gives such a file no media type. */
const PICTURE_NAME = /\.(png|jpe?g|gif|webp|avif|heic|heif|tiff?|bmp)$/i;

/**
 * What a chosen file is when it shows an invoice rather than being one: a picture, such as a
 * photo or a screenshot, or a PDF. The validator checks the XML, so neither is worth sending;
 * null for any other file, which the validator judges. The browser's media type says, or else
 * the file's name.
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

/** A page of the organization's invoices, the newest first; ``after`` continues a list. */
export function listInvoices({
  after,
  signal,
}: { after?: string | null; signal?: AbortSignal } = {}): Promise<InvoicePage> {
  const query = new URLSearchParams({ limit: String(PAGE_SIZE) });
  if (after) {
    query.set("after", after);
  }
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
