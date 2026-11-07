import type { Schemas } from "@/lib/api";
import { authorized } from "@/lib/session";

/** The visitor's organization: its name, and how long it keeps its stored invoices. */
export type Organization = Schemas["OrganizationSettings"];

/** The periods an owner chooses from, in days: a month to ten years. */
export const RETENTION_PERIODS = [30, 90, 180, 365, 730, 1825, 3650] as const;

const DAY_MS = 86_400_000;

/** The signed-in visitor's organization (`GET /organization`). */
export function getOrganization(signal?: AbortSignal): Promise<Organization> {
  return authorized<Organization>("/organization", { signal });
}

/**
 * Has the organization keep each stored invoice ``days`` after it was stored, or every invoice
 * until a member deletes it with null; only an owner may. The answer is the organization.
 */
export function setInvoiceRetention(
  days: number | null,
): Promise<Organization> {
  return authorized<Organization>("/organization", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ invoice_retention_days: days }),
  });
}

/**
 * Whether a change of the period from ``before`` to ``after`` days, null for none, can delete
 * invoices: a period where there was none, or a shorter one.
 */
export function deletesInvoices(
  before: number | null,
  after: number | null,
): boolean {
  return after !== null && (before === null || after < before);
}

/** The moment before which the invoices a period of ``days`` deletes were stored. */
export function storedBefore(days: number, now: Date): Date {
  return new Date(now.getTime() - days * DAY_MS);
}
