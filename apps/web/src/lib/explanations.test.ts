import { describe, expect, it, vi } from "vitest";

import { REQUEST_TIMEOUT_MS } from "@/lib/api";
import { json, keepSession, stubApi } from "@/test/api";
import { explained } from "@/test/invoices";

import {
  cyrillic,
  EXPLAIN_TIMEOUT_MS,
  explainInvoice,
  keptExplanations,
  languageOf,
} from "./explanations";

/** An answer that never comes: the request ends only when its signal aborts it. */
function silence(signal: AbortSignal | null | undefined): Promise<Response> {
  return new Promise((_, reject) => {
    signal?.addEventListener("abort", () => reject(signal.reason));
  });
}

describe("The explanations the API keeps", () => {
  it("are read with a GET, which asks the language model nothing", async () => {
    keepSession();
    const asked = stubApi(() => json(200, explained()));

    const kept = await keptExplanations("i-1", "sr");

    expect(kept?.model).toBe("test/quoting");
    expect(
      asked.map(({ method, path, search }) => `${method} ${path}${search}`),
    ).toEqual(["GET /invoices/i-1/explanations?language=sr"]);
  });

  it.each([
    ["none are kept", () => new Response(null, { status: 204 })],
    ["the invoice is gone", () => json(404, { detail: "no such invoice" })],
    ["the API fails", () => json(500, { detail: "Internal Server Error" })],
    ["the API does not answer", () => Promise.reject(new TypeError("Failed"))],
  ])("are none when %s: asking reads them too", async (_, answer) => {
    keepSession();
    stubApi(answer);

    expect(await keptExplanations("i-1", "sr")).toBeNull();
  });

  it("are not read once the page no longer wants them", async () => {
    keepSession();
    const asked = stubApi(({ signal }) => silence(signal));
    const leaving = new AbortController();

    const reading = keptExplanations("i-1", "sr", leaving.signal).catch(
      (thrown: unknown) => thrown,
    );
    await vi.waitFor(() => expect(asked).toHaveLength(1));
    leaving.abort(new DOMException("left", "AbortError"));

    expect(await reading).toMatchObject({ name: "AbortError" });
  });
});

describe("The explanations of a stored invoice", () => {
  it("are asked of the API in the language given, with nothing in the body", async () => {
    keepSession();
    const asked = stubApi(() => json(200, explained({ language: "en" })));

    const answer = await explainInvoice("i-1", "en");

    expect(answer.language).toBe("en");
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
        path: "/invoices/i-1/explanations",
        search: "?language=en",
        body: undefined,
      },
    ]);
    expect(asked[0].headers.get("Authorization")).toBe("Bearer access-2");
  });

  it("are asked for by the invoice's id, which stays one segment of the path", async () => {
    keepSession();
    const asked = stubApi(() => json(200, explained()));

    await explainInvoice("../members", "sr");

    expect(asked.map((request) => request.path)).toEqual([
      "/invoices/..%2Fmembers/explanations",
    ]);
  });

  it("have a minute to be written, not the usual ten seconds", async () => {
    vi.useFakeTimers();
    try {
      keepSession();
      const asked = stubApi(({ signal }) => silence(signal));

      const explaining = explainInvoice("i-1", "sr").catch(
        (thrown: unknown) => thrown,
      );
      await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS);

      expect(asked).toHaveLength(1);
      expect(asked[0].signal?.aborted).toBe(false);

      await vi.advanceTimersByTimeAsync(
        EXPLAIN_TIMEOUT_MS - REQUEST_TIMEOUT_MS,
      );

      expect(await explaining).toMatchObject({ name: "TimeoutError" });
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("The language of the explanations", () => {
  it("is the page's: Serbian, or English", () => {
    expect(languageOf("sr-Latn")).toBe("sr");
    expect(languageOf("en")).toBe("en");
  });
});

describe("Text in Cyrillic", () => {
  it("is marked as Serbian in Cyrillic, and nothing else is", () => {
    expect(cyrillic("Члан 2.")).toBe("sr-Cyrl");
    expect(cyrillic("Seller VAT identifier — ПИБ продавца")).toBe("sr-Cyrl");
    expect(cyrillic("BT-31")).toBeUndefined();
  });
});
