import type { Schemas } from "@/lib/api";
import { authorized } from "@/lib/session";

/** A repair of a stored invoice: its patches, what became of each, the diff and the report. */
export type Repair = Schemas["RepairOut"];
/** A repair as the invoice's history lists it, without its patches, diff or report. */
export type ListedRepair = Schemas["RepairListed"];
/** Where a repair stands: waiting for a person, approved, rejected, or overtaken by another. */
export type RepairStatus = Schemas["RepairStatus"];
/** What became of one patch of a repair, with the patch: where, what, the new text and why. */
export type Outcome = Schemas["Outcome"];

const repairsOf = (invoiceId: string) =>
  `/invoices/${encodeURIComponent(invoiceId)}/repairs`;

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
