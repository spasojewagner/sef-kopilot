import { describe, expect, it, vi } from "vitest";

import { ApiError, REQUEST_TIMEOUT_MS } from "@/lib/api";
import { json, keepSession, stubApi } from "@/test/api";
import { listedRepair, repair } from "@/test/repairs";

import {
  conflictOf,
  getRepair,
  listRepairs,
  SUGGEST_TIMEOUT_MS,
  suggestRepair,
} from "./repairs";

/** An answer that never comes: the request ends only when its signal aborts it. */
function silence(signal: AbortSignal | null | undefined): Promise<Response> {
  return new Promise((_, reject) => {
    signal?.addEventListener("abort", () => reject(signal.reason));
  });
}

describe("A stored invoice's repairs", () => {
  it("are listed from the invoice's own path", async () => {
    keepSession();
    const asked = stubApi(() => json(200, [listedRepair()]));

    const repairs = await listRepairs("i-1");

    expect(repairs).toEqual([listedRepair()]);
    expect(asked.map(({ method, path }) => `${method} ${path}`)).toEqual([
      "GET /invoices/i-1/repairs",
    ]);
  });

  it("are read one at a time, each id kept to one segment of the path", async () => {
    keepSession();
    const asked = stubApi(() => json(200, repair()));

    await getRepair("../members", "../keys");

    expect(asked.map((request) => request.path)).toEqual([
      "/invoices/..%2Fmembers/repairs/..%2Fkeys",
    ]);
  });
});

describe("A repair the language model suggests", () => {
  it("is asked of the API in the page's language, with nothing in the body", async () => {
    keepSession();
    const asked = stubApi(() => json(201, repair()));

    await expect(suggestRepair("../members", "en")).resolves.toEqual(repair());

    expect(
      asked.map(({ method, path, search, body }) => ({
        method,
        path,
        search,
        body,
      })),
    ).toEqual([
      {
        method: "POST",
        path: "/invoices/..%2Fmembers/repairs/suggestion",
        search: "?language=en",
        body: undefined,
      },
    ]);
  });

  it("has a minute to be written, not the usual ten seconds", async () => {
    vi.useFakeTimers();
    try {
      keepSession();
      const asked = stubApi(({ signal }) => silence(signal));

      const suggesting = suggestRepair("i-1", "sr").catch(
        (thrown: unknown) => thrown,
      );
      await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS);

      expect(asked).toHaveLength(1);
      expect(asked[0].signal?.aborted).toBe(false);

      await vi.advanceTimersByTimeAsync(
        SUGGEST_TIMEOUT_MS - REQUEST_TIMEOUT_MS,
      );

      expect(await suggesting).toMatchObject({ name: "TimeoutError" });
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("A request about repairs that the API refuses", () => {
  it("says why with a 409's reason, and only then", () => {
    const conflict = (status: number, body: unknown) =>
      conflictOf(new ApiError(status, "refused", { body }));

    expect(conflict(409, { detail: "...", reason: "too-many-waiting" })).toBe(
      "too-many-waiting",
    );
    expect(conflict(409, { detail: "the repair is approved" })).toBeNull();
    expect(conflict(422, { detail: "...", reason: "decided" })).toBeNull();
    expect(conflictOf(new TypeError("Failed to fetch"))).toBeNull();
  });
});
