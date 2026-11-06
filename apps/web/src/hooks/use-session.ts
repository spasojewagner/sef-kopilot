"use client";

import { useSyncExternalStore } from "react";

import {
  currentSession,
  serverSession,
  subscribe,
  type Session,
} from "@/lib/session";

/**
 * The visitor's session, kept up to date as it changes in this tab or in another. A page
 * rendered at build time knows no session: it is `unknown` until the browser takes over.
 */
export function useSession(): Session {
  return useSyncExternalStore(subscribe, currentSession, serverSession);
}
