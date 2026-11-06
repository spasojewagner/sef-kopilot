import { describe, expect, it, vi } from "vitest";

import { REQUEST_TIMEOUT_MS } from "@/lib/api";
import { json, keepSession, stubApi } from "@/test/api";
import { storedInvoice } from "@/test/invoices";

import { getInvoice, storeInvoice, UPLOAD_TIMEOUT_MS } from "./invoices";

/** An answer that never comes: the request ends only when its signal aborts it. */
function silence(signal: AbortSignal | null | undefined): Promise<Response> {
  return new Promise((_, reject) => {
    signal?.addEventListener("abort", () => reject(signal.reason));
  });
}

describe("A stored invoice", () => {
  it("is asked for by its id, which stays one segment of the path", async () => {
    keepSession();
    const asked = stubApi(() => json(200, storedInvoice()));

    // Whatever the id holds: `/invoices/../members` would be the browser's `/members`.
    await getInvoice("../members");

    expect(asked.map((request) => request.path)).toEqual([
      "/invoices/..%2Fmembers",
    ]);
  });
});

describe("An upload", () => {
  it("has a minute to be answered, not the usual ten seconds", async () => {
    vi.useFakeTimers();
    try {
      keepSession();
      const asked = stubApi(({ signal }) => silence(signal));

      const upload = storeInvoice(new Blob(["<Invoice/>"])).catch(
        (thrown: unknown) => thrown,
      );
      await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS);

      expect(asked).toHaveLength(1);
      expect(asked[0].signal?.aborted).toBe(false);

      await vi.advanceTimersByTimeAsync(UPLOAD_TIMEOUT_MS - REQUEST_TIMEOUT_MS);

      expect(await upload).toMatchObject({ name: "TimeoutError" });
    } finally {
      vi.useRealTimers();
    }
  });
});
