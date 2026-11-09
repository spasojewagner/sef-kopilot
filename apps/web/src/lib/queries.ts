import {
  infiniteQueryOptions,
  type QueryClient,
  queryOptions,
} from "@tanstack/react-query";

import { listKeys } from "@/lib/api-keys";
import { getHealth } from "@/lib/api";
import { getBilling, listCreditEntries } from "@/lib/billing";
import {
  type Explained,
  explainInvoice,
  keptExplanations,
  type Language,
} from "@/lib/explanations";
import { getInvoice, listInvoices } from "@/lib/invoices";
import { getAuthorizationRequest } from "@/lib/oauth";
import { getOrganization } from "@/lib/organization";
import { getRepair, listRepairs } from "@/lib/repairs";
import { isWatched, listSubmissions } from "@/lib/sef";
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

/** Whether storing an invoice costs a credit, and how many the organization holds. */
export const billingQuery = queryOptions({
  queryKey: ["billing"],
  queryFn: ({ signal }) => getBilling(signal),
});

/** The latest changes of the organization's credits, which only an owner sees. */
export const creditEntriesQuery = queryOptions({
  queryKey: ["billing", "entries"],
  queryFn: ({ signal }) => listCreditEntries(signal),
});

/** The API keys the visitor may see that still work, the newest first. */
export const apiKeysQuery = queryOptions({
  queryKey: ["keys"],
  queryFn: ({ signal }) => listKeys(signal),
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
 * The explanations of the stored invoice ``id``'s report in ``language``, as far as the visit
 * knows them: those the API keeps for the report, read at once since reading asks the language
 * model nothing (ADR-0040), or null when none are kept. {@link askForExplanations} writes them
 * under the same key. Never asked again by themselves, and kept until the page is reloaded or
 * the visitor signs out. Under the invoice's key, so that what changes the invoice drops them
 * too.
 */
export function explanationsQuery(id: string, language: Language) {
  return queryOptions({
    queryKey: ["invoices", "one", id, "explanations", language],
    queryFn: ({ signal }): Promise<Explained | null> =>
      keptExplanations(id, language, signal),
    staleTime: Infinity,
    gcTime: Infinity,
    retry: false,
  });
}

/**
 * Asks for the explanations of the stored invoice ``id``'s report in ``language``, which may cost
 * requests to the language model, and keeps the answer, or the failure, under the key of
 * {@link explanationsQuery}, where the page reads them.
 */
export function askForExplanations(
  client: QueryClient,
  id: string,
  language: Language,
): Promise<Explained | null> {
  return client.fetchQuery({
    ...explanationsQuery(id, language),
    queryFn: ({ signal }) => explainInvoice(id, language, signal),
    // What the visit knows, none kept say, is fresh: asking fetches all the same.
    staleTime: 0,
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

/** How often the page reads again where an invoice the API watches stands in SEF. */
export const WATCH_INTERVAL_MS = 30_000;

/**
 * Each time the stored invoice ``invoiceId`` was sent to SEF, the newest first, read again every
 * half a minute while the API still asks SEF where the latest stands, so that the page shows
 * what SEF says without being reloaded. Under the invoice's key, so that deleting it drops them.
 */
export function submissionsQuery(invoiceId: string) {
  return queryOptions({
    queryKey: ["invoices", "one", invoiceId, "sef"],
    queryFn: ({ signal }) => listSubmissions(invoiceId, signal),
    refetchInterval: (query) =>
      isWatched(query.state.data?.[0]) ? WATCH_INTERVAL_MS : false,
  });
}

/** What an MCP client asks to do for the visitor, while the request waits for their decision. */
export function authorizationRequestQuery(id: string) {
  return queryOptions({
    queryKey: ["oauth", "requests", id],
    queryFn: ({ signal }) => getAuthorizationRequest(id, signal),
  });
}
