import { infiniteQueryOptions, queryOptions } from "@tanstack/react-query";

import { getHealth } from "@/lib/api";
import { explainInvoice, type Language } from "@/lib/explanations";
import { getInvoice, listInvoices } from "@/lib/invoices";
import { getOrganization } from "@/lib/organization";
import { getRepair, listRepairs } from "@/lib/repairs";
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

/**
 * Whether the API answers, and which version it runs. Not asked again when it fails: a check of
 * an API that may be asleep already waits for it, for up to two minutes.
 */
export const healthQuery = queryOptions({
  queryKey: ["api", "health"],
  queryFn: ({ signal }) => getHealth(signal),
  retry: false,
});

/**
 * Who the signed-in visitor is, as the API says now (`GET /auth/me`); asking also proves that
 * the session is alive, and ends it here when it is not.
 */
export const meQuery = queryOptions({
  queryKey: ["visitor", "me"],
  queryFn: ({ signal }) => authorized<Identity>("/auth/me", { signal }),
});

/** The visitor's organization, and how long it keeps its stored invoices. */
export const organizationQuery = queryOptions({
  queryKey: ["organization"],
  queryFn: ({ signal }) => getOrganization(signal),
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

/**
 * The explanations of the stored invoice ``id``'s report, in ``language``. Each costs requests
 * to the language model, so they are written only when the visitor asks (the page passes
 * ``enabled``), never asked for again by themselves, and kept until the page is reloaded or the
 * visitor signs out. Under the invoice's key, so that what changes the invoice drops them too.
 */
export function explanationsQuery(id: string, language: Language) {
  return queryOptions({
    queryKey: ["invoices", "one", id, "explanations", language],
    queryFn: ({ signal }) => explainInvoice(id, language, signal),
    staleTime: Infinity,
    gcTime: Infinity,
    retry: false,
  });
}

/** The repairs of the stored invoice ``invoiceId``, the latest first. */
export function repairsQuery(invoiceId: string) {
  return queryOptions({
    queryKey: ["invoices", "one", invoiceId, "repairs"],
    queryFn: ({ signal }) => listRepairs(invoiceId, signal),
  });
}

/** The repair ``repairId`` of the stored invoice ``invoiceId``, with its diff and report. */
export function repairQuery(invoiceId: string, repairId: string) {
  return queryOptions({
    queryKey: ["invoices", "one", invoiceId, "repairs", repairId],
    queryFn: ({ signal }) => getRepair(invoiceId, repairId, signal),
  });
}
