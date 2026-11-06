"use client";

import {
  isServer,
  QueryClient,
  QueryClientProvider,
  useQueryClient,
} from "@tanstack/react-query";
import { useEffect, useRef, type ReactNode } from "react";

import { useSession } from "@/hooks/use-session";
import { ApiError } from "@/lib/api";
import { isAboutTheApi } from "@/lib/queries";

/** The defaults of every question the pages ask the API. */
export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // An answer stays fresh for a minute: going from page to page does not ask again.
        staleTime: 60_000,
        // One more try, a second later, when the API could not be reached or failed; none
        // when it refused the request, which would only refuse it again.
        retry: (failures, error) =>
          failures < 1 && !(error instanceof ApiError && error.status < 500),
      },
    },
  });
}

let browserClient: QueryClient | undefined;

/**
 * A new cache for each render on the server, so that no visitor sees another's answers, and
 * one for the whole visit in the browser. The browser's is kept outside React, which throws
 * away the state of a tree that suspends before it is first shown.
 */
function queryClient(): QueryClient {
  if (isServer) {
    return makeQueryClient();
  }
  browserClient ??= makeQueryClient();
  return browserClient;
}

/**
 * Forgets a visitor's answers when they sign out, here or in another tab, or another visitor
 * signs in: the next person at this browser does not see them. What the API says about itself
 * is the same for everyone, and kept.
 */
export function ForgetAVisitorsAnswers() {
  const client = useQueryClient();
  const session = useSession();
  const visitor =
    session.status === "signed-in"
      ? `${session.identity.user.id} in ${session.identity.organization.id}`
      : session.status;
  const last = useRef(visitor);
  useEffect(() => {
    const before = last.current;
    last.current = visitor;
    if (before !== visitor && before !== "unknown" && before !== "signed-out") {
      client.removeQueries({
        predicate: (query) => !isAboutTheApi(query.queryKey),
      });
    }
  }, [client, visitor]);
  return null;
}

/** Gives the pages' client components one cache of the API's answers. */
export function QueryProvider({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient()}>
      <ForgetAVisitorsAnswers />
      {children}
    </QueryClientProvider>
  );
}
