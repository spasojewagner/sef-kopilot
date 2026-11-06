import { infiniteQueryOptions, queryOptions } from "@tanstack/react-query";

import { getHealth } from "@/lib/api";
import { getInvoice, listInvoices } from "@/lib/invoices";
import { authorized, type Identity } from "@/lib/session";

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

/**
 * Who the signed-in visitor is, as the API says now (`GET /auth/me`); asking also proves that
 * the session is alive, and ends it here when it is not.
 */
export const meQuery = queryOptions({
  queryKey: ["visitor", "me"],
  queryFn: ({ signal }) => authorized<Identity>("/auth/me", { signal }),
});

/** The organization's invoices, the newest first, a page at a time. */
export const invoicesQuery = infiniteQueryOptions({
  queryKey: ["invoices", "list"],
  queryFn: ({ pageParam, signal }) =>
    listInvoices({ after: pageParam, signal }),
  initialPageParam: null as string | null,
  getNextPageParam: (page) => page.next,
});

/** A stored invoice with the validator's latest report on it. */
export function invoiceQuery(id: string) {
  return queryOptions({
    queryKey: ["invoices", "one", id],
    queryFn: ({ signal }) => getInvoice(id, signal),
  });
}
