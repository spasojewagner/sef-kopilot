import type { Schemas } from "@/lib/api";
import { authorized } from "@/lib/session";

/** An API key, without the key itself: what it is for, what it allows and when it was used. */
export type ApiKey = Schemas["KeyOut"];

/** A key as it is issued: the one time the key itself is shown. */
export type IssuedKey = Schemas["IssuedKey"];

/** A permission a key may hold. */
export type KeyPermission =
  "invoices:validate" | "invoices:submit" | "invoices:manage";

/** The permissions a key may hold, in the order the page offers them. */
export const KEY_PERMISSIONS: readonly KeyPermission[] = [
  "invoices:validate",
  "invoices:submit",
  "invoices:manage",
];

/** The permissions of a key that each role grants (the API's `ROLE_PERMISSIONS`). */
export const GRANTED: Record<string, readonly KeyPermission[]> = {
  owner: KEY_PERMISSIONS,
  accountant: KEY_PERMISSIONS,
  client: ["invoices:validate", "invoices:submit"],
};

/** The keys the visitor may see that still work, the newest first (`GET /api-keys`). */
export function listKeys(signal?: AbortSignal): Promise<ApiKey[]> {
  return authorized<ApiKey[]>("/api-keys", { signal });
}

/** Issues a key for a machine that acts for the visitor (`POST /api-keys`). */
export function issueKey(asked: {
  name: string;
  permissions: KeyPermission[];
  expiresAt: Date | null;
}): Promise<IssuedKey> {
  return authorized<IssuedKey>("/api-keys", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: asked.name,
      permissions: asked.permissions,
      expires_at: asked.expiresAt?.toISOString() ?? null,
    }),
  });
}

/** Revokes a key at once (`DELETE /api-keys/{id}`). */
export function revokeKey(id: string): Promise<void> {
  return authorized<void>(`/api-keys/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}
