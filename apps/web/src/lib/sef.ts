import { ApiError, type Schemas } from "@/lib/api";
import { authorized } from "@/lib/session";

/** A stored invoice sent to SEF, and what SEF answered (ADR-0051). */
export type Submission = Schemas["Submission"];

/** Why the API did not send an invoice, as its 409 says. */
export type SendReason = Schemas["SendConflict"]["reason"];

/**
 * How long sending may take: the API validates the invoice again, then asks SEF up to three
 * times, each for up to half a minute, before it answers that SEF gave no answer.
 */
export const SEND_TIMEOUT_MS = 120_000;

/** The statuses after which SEF changes nothing more, and the API stops asking (`FINAL`). */
const FINAL: ReadonlySet<string> = new Set([
  "Approved",
  "Rejected",
  "Cancelled",
  "Storno",
  "Deleted",
]);

const sefOf = (invoiceId: string) =>
  `/invoices/${encodeURIComponent(invoiceId)}/sef`;

/** Each time the invoice was sent to SEF, the newest first (`GET /invoices/{id}/sef`). */
export function listSubmissions(
  invoiceId: string,
  signal?: AbortSignal,
): Promise<Submission[]> {
  return authorized<Submission[]>(sefOf(invoiceId), { signal });
}

/**
 * Sends the stored invoice to SEF's demo environment in the organization's name
 * (`POST /invoices/{id}/sef`): the submission as SEF answered it, or an {@link ApiError} whose
 * {@link reasonOf} says why nothing was sent.
 */
export function sendToSef(invoiceId: string): Promise<Submission> {
  return authorized<Submission>(sefOf(invoiceId), {
    method: "POST",
    timeoutMs: SEND_TIMEOUT_MS,
  });
}

/** The reason the API gave for not sending an invoice, with 409; none otherwise. */
export function reasonOf(error: unknown): SendReason | null {
  if (!(error instanceof ApiError) || error.status !== 409) {
    return null;
  }
  const body = error.body as { reason?: unknown } | null;
  return typeof body?.reason === "string" ? (body.reason as SendReason) : null;
}

/** Whether SEF will say nothing more about an invoice that stands at ``status``. */
export function isFinal(status: string | null): boolean {
  return status !== null && FINAL.has(status);
}

/** How long the API asks SEF where an imported invoice stands (`WATCHED_FOR`). */
const WATCHED_FOR_MS = 30 * 86_400_000;

/**
 * Whether the API still asks SEF where the latest submission stands, so that the page should
 * read it again: imported less than thirty days before ``now``, and not yet final.
 */
export function isWatched(
  latest: Submission | undefined,
  now: number = Date.now(),
): boolean {
  return (
    latest?.state === "imported" &&
    !isFinal(latest.sef_status) &&
    now - Date.parse(latest.sent_at) < WATCHED_FOR_MS
  );
}
