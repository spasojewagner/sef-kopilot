"use client";

import { useSyncExternalStore } from "react";

import { isApiWaking, subscribeToApiWaking } from "@/lib/api";

/**
 * Whether the API is waking up: the pages have been waiting a few seconds for an API that had
 * not answered for a while (ADR-0036). A page rendered at build time knows of no wait.
 */
export function useApiWaking(): boolean {
  return useSyncExternalStore(subscribeToApiWaking, isApiWaking, () => false);
}
