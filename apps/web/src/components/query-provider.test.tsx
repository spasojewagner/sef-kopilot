import { queryOptions } from "@tanstack/react-query";
import { act } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { healthQuery } from "@/lib/queries";
import { signOut, STORAGE_KEY } from "@/lib/session";
import { renderIn, testQueryClient } from "@/test/render";

import { ForgetAVisitorsAnswers, makeQueryClient } from "./query-provider";

/** Whether a question that failed ``failures`` times with ``error`` is asked again. */
function askedAgain(failures: number, error: Error): boolean {
  const retry = makeQueryClient().getDefaultOptions().queries?.retry;
  if (typeof retry !== "function") {
    throw new Error("the retry policy is not a function");
  }
  return retry(failures, error);
}

describe("The pages' questions to the API", () => {
  it("are asked once more when the API could not be reached or failed", () => {
    expect(askedAgain(0, new TypeError("Failed to fetch"))).toBe(true);
    expect(askedAgain(0, new ApiError(503, "Service Unavailable"))).toBe(true);
  });

  it("are not asked a third time", () => {
    expect(askedAgain(1, new TypeError("Failed to fetch"))).toBe(false);
    expect(askedAgain(1, new ApiError(500, "Internal Server Error"))).toBe(
      false,
    );
  });

  it("are not asked again when the API refused them", () => {
    expect(askedAgain(0, new ApiError(404, "no such invoice"))).toBe(false);
    expect(askedAgain(0, new ApiError(422, "Field required"))).toBe(false);
  });

  it("keep their answers fresh for a minute", () => {
    expect(makeQueryClient().getDefaultOptions().queries?.staleTime).toBe(
      60_000,
    );
  });
});

const invoices = queryOptions({
  queryKey: ["invoices"],
  queryFn: () => ["an invoice"],
});

const ALICE = {
  user: { id: "u-alice", email: "alice@primer.example" },
  organization: { id: "o-primer", name: "Primer d.o.o." },
  role: "owner",
};

function keep(refreshToken: string, who: typeof ALICE = ALICE) {
  localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({
      refreshToken,
      refreshExpiresAt: Date.now() + 3_600_000,
      identity: who,
    }),
  );
}

/** Another tab wrote the session, and this one hears of it. */
function anotherTabWrote() {
  act(() => {
    window.dispatchEvent(
      new StorageEvent("storage", {
        key: STORAGE_KEY,
        newValue: localStorage.getItem(STORAGE_KEY),
      }),
    );
  });
}

/** A cache with a visitor's invoices and the API's health in it. */
function cacheWithAnswers() {
  const client = testQueryClient();
  client.setQueryData(invoices.queryKey, ["an invoice"]);
  client.setQueryData(healthQuery.queryKey, {
    status: "ok",
    service: "sef-kopilot-api",
    version: "0.2.0",
    public_demo: false,
  });
  return client;
}

describe("A visitor's answers", () => {
  it("are forgotten when the visitor signs out, and what the API says of itself is kept", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(null, { status: 204 })),
    );
    keep("refresh-1");
    const client = cacheWithAnswers();
    renderIn("en", <ForgetAVisitorsAnswers />, client);
    expect(client.getQueryData(invoices.queryKey)).toEqual(["an invoice"]);

    await act(() => signOut());

    expect(client.getQueryData(invoices.queryKey)).toBeUndefined();
    expect(client.getQueryData(healthQuery.queryKey)).toBeDefined();
  });

  it("are forgotten when another visitor signs in, in another tab", () => {
    keep("refresh-alice");
    const client = cacheWithAnswers();
    renderIn("en", <ForgetAVisitorsAnswers />, client);

    keep("refresh-bob", {
      ...ALICE,
      user: { id: "u-bob", email: "bob@primer.example" },
    });
    anotherTabWrote();

    expect(client.getQueryData(invoices.queryKey)).toBeUndefined();
  });

  it("are kept when another tab refreshes the same visitor's session", () => {
    keep("refresh-1");
    const client = cacheWithAnswers();
    renderIn("en", <ForgetAVisitorsAnswers />, client);

    keep("refresh-2");
    anotherTabWrote();

    expect(client.getQueryData(invoices.queryKey)).toEqual(["an invoice"]);
  });
});
