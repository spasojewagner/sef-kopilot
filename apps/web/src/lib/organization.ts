import type { Schemas } from "@/lib/api";
import { authorized } from "@/lib/session";

/** The visitor's organization: its name, and how long it keeps its stored invoices. */
export type Organization = Schemas["OrganizationSettings"];

/** The signed-in visitor's organization (`GET /organization`). */
export function getOrganization(signal?: AbortSignal): Promise<Organization> {
  return authorized<Organization>("/organization", { signal });
}
