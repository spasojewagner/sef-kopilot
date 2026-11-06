import { queryOptions } from "@tanstack/react-query";

import { getHealth } from "@/lib/api";

/**
 * The questions the pages ask the API, each with the key its answers are kept under. A page
 * asks with `useQuery(healthQuery)`; the key also names the answer to refresh or to forget.
 *
 * A key that starts with `api` holds what the API says about itself, the same for every
 * visitor. Every other key holds a visitor's data, which is forgotten when they sign out.
 */

/** Whether the answers under ``key`` are the same for every visitor. */
export function isAboutTheApi(key: readonly unknown[]): boolean {
  return key[0] === "api";
}

/** Whether the API answers, and which version it runs. */
export const healthQuery = queryOptions({
  queryKey: ["api", "health"],
  queryFn: ({ signal }) => getHealth(signal),
});
