"use client";

import { useQuery } from "@tanstack/react-query";

import { useSession } from "@/hooks/use-session";
import { meQuery } from "@/lib/queries";
import type { Identity } from "@/lib/session";

/**
 * Who the visitor is, with the role the API says they hold now, or the one they held when they
 * signed in until it has said: a role changed since is the API's to enforce, and the page
 * follows it once it knows. Null for a visitor who is not signed in.
 */
export function useIdentity(): Identity | null {
  const session = useSession();
  const me = useQuery({ ...meQuery, enabled: session.status === "signed-in" });
  return session.status === "signed-in" ? (me.data ?? session.identity) : null;
}
