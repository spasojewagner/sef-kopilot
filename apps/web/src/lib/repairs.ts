import { ApiError, type Schemas } from "@/lib/api";
import type { Language } from "@/lib/explanations";
import { authorized } from "@/lib/session";

/** A repair of a stored invoice: its patches, what became of each, the diff and the report. */
export type Repair = Schemas["RepairOut"];
/** A repair as the invoice's history lists it, without its patches, diff or report. */
export type ListedRepair = Schemas["RepairListed"];
/** Where a repair stands: waiting for a person, approved, rejected, or overtaken by another. */
export type RepairStatus = Schemas["RepairStatus"];
/** What became of one patch of a repair, with the patch: where, what, the new text and why. */
export type Outcome = Schemas["Outcome"];
/** Why the API refused a request about repairs with 409, which a page answers by. */
export type ConflictReason = Schemas["RepairConflict"]["reason"];

/**
 * How long the page waits for a suggested repair. The API gives the model's rounds 20 s by
 * default (`SEF_REPAIR_SECONDS`), each followed by a validation, and may first have to wake up.
 */
export const SUGGEST_TIMEOUT_MS = 60_000;

const repairsOf = (invoiceId: string) =>
  `/invoices/${encodeURIComponent(invoiceId)}/repairs`;

/** The repairs of the stored invoice ``invoiceId``, the latest first. */
export function listRepairs(
  invoiceId: string,
  signal?: AbortSignal,
): Promise<ListedRepair[]> {
  return authorized<ListedRepair[]>(repairsOf(invoiceId), { signal });
}

/** The repair ``repairId`` of the stored invoice ``invoiceId``. */
export function getRepair(
  invoiceId: string,
  repairId: string,
  signal?: AbortSignal,
): Promise<Repair> {
  return authorized<Repair>(
    `${repairsOf(invoiceId)}/${encodeURIComponent(repairId)}`,
    { signal },
  );
}

/**
 * Asks the language model for a repair of the stored invoice ``invoiceId``'s fatal violations,
 * its patches' reasons in ``language``. The API keeps it as a repair the visitor proposes, and
 * the invoice does not change. A POST: each request spends the model's requests.
 */
export function suggestRepair(
  invoiceId: string,
  language: Language,
): Promise<Repair> {
  const query = new URLSearchParams({ language });
  return authorized<Repair>(`${repairsOf(invoiceId)}/suggestion?${query}`, {
    method: "POST",
    timeoutMs: SUGGEST_TIMEOUT_MS,
  });
}

/** A person's decision on a repair: its approval, or its rejection. */
export type Decision = "approval" | "rejection";

/**
 * How long the page waits for a decision. An approval applies the patches again and validates
 * what they leave, as an upload does; a rejection only records it.
 */
export const DECISION_TIMEOUT_MS = 60_000;

/**
 * Records the visitor's ``decision`` on the repair ``repairId`` of the stored invoice
 * ``invoiceId``, which the API takes only in person, never from an API key. An approval makes
 * the invoice the patched document, with its report, and supersedes the other repairs that
 * waited for it; a rejection leaves the invoice as it is. The answer is the decided repair.
 */
export function decideRepair(
  invoiceId: string,
  repairId: string,
  decision: Decision,
): Promise<Repair> {
  return authorized<Repair>(
    `${repairsOf(invoiceId)}/${encodeURIComponent(repairId)}/${decision}`,
    { method: "POST", timeoutMs: DECISION_TIMEOUT_MS },
  );
}

/** The reason the API gave for refusing a request about repairs with 409; none otherwise. */
export function conflictOf(error: unknown): ConflictReason | null {
  if (!(error instanceof ApiError) || error.status !== 409) {
    return null;
  }
  const body = error.body as { reason?: unknown } | null;
  return typeof body?.reason === "string"
    ? (body.reason as ConflictReason)
    : null;
}
