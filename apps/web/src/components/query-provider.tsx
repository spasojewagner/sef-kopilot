"use client";

import {
  isServer,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import type { ReactNode } from "react";

import { ApiError } from "@/lib/api";

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

/** Gives the pages' client components one cache of the API's answers. */
export function QueryProvider({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient()}>{children}</QueryClientProvider>
  );
}
