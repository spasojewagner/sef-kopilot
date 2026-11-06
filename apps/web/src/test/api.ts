import { vi } from "vitest";

import { STORAGE_KEY } from "@/lib/session";

/** A visitor of the tests, signed in to their organization. */
export const ALICE = {
  user: { id: "u-alice", email: "alice@primer.example" },
  organization: { id: "o-primer", name: "Primer d.o.o." },
  role: "owner" as const,
};

/** Keeps a session for {@link ALICE}, as a sign-in in an earlier visit would have. */
export function keepSession(): void {
  localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({
      refreshToken: "refresh-1",
      refreshExpiresAt: Date.now() + 3_600_000,
      identity: ALICE,
    }),
  );
}

export function json(
  status: number,
  body: unknown,
  headers: HeadersInit = {},
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

/** What a test's API was asked. */
export interface Asked {
  method: string;
  path: string;
  search: string;
  headers: Headers;
  body: BodyInit | null | undefined;
  signal: AbortSignal | null | undefined;
}

/**
 * An API that answers a refresh for {@link ALICE}, and every other request with ``answer``;
 * what it was asked is returned.
 */
export function stubApi(
  answer: (asked: Asked) => Response | Promise<Response>,
): Asked[] {
  const asked: Asked[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const url = new URL(String(input));
      const request: Asked = {
        method: init.method ?? "GET",
        path: url.pathname,
        search: url.search,
        headers: new Headers(init.headers),
        body: init.body,
        signal: init.signal,
      };
      if (request.path === "/auth/refresh") {
        return json(200, {
          token_type: "bearer",
          access_token: "access-2",
          expires_in: 900,
          refresh_token: "refresh-2",
          refresh_expires_in: 2_592_000,
          ...ALICE,
        });
      }
      asked.push(request);
      return answer(request);
    }),
  );
  return asked;
}
