import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import {
  explanationsQuery,
  healthQuery,
  invoiceQuery,
  invoicesQuery,
  isAboutTheApi,
  meQuery,
  repairQuery,
  repairsQuery,
} from "./queries";

describe("The question of the API's health", () => {
  it("is asked of /health and kept under its key", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", "https://api.example");
    const answer = {
      status: "ok",
      service: "sef-kopilot-api",
      version: "0.2.0",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify(answer), { status: 200 })),
    );
    const client = new QueryClient();

    await expect(client.fetchQuery(healthQuery)).resolves.toEqual(answer);

    expect(healthQuery.queryKey).toEqual(["api", "health"]);
    expect(client.getQueryData(healthQuery.queryKey)).toEqual(answer);
    expect(fetch).toHaveBeenCalledWith(
      "https://api.example/health",
      expect.anything(),
    );
  });

  it("stops its request when no page needs the answer any more", async () => {
    const fetch = vi.fn(
      (input: RequestInfo | URL, init: RequestInit = {}) =>
        new Promise<Response>((_, reject) => {
          init.signal?.addEventListener("abort", () =>
            reject(init.signal?.reason),
          );
        }),
    );
    vi.stubGlobal("fetch", fetch);
    const client = new QueryClient();

    const asked = client.fetchQuery(healthQuery).catch(() => undefined);
    await vi.waitFor(() => expect(fetch).toHaveBeenCalled());
    await client.cancelQueries({ queryKey: healthQuery.queryKey });
    await asked;

    expect(fetch.mock.calls[0][1]?.signal?.aborted).toBe(true);
  });
});

describe("The keys of the answers", () => {
  it("say which answers are the same for every visitor, and which are a visitor's", () => {
    expect(isAboutTheApi(healthQuery.queryKey)).toBe(true);
    expect(isAboutTheApi(meQuery.queryKey)).toBe(false);
    expect(isAboutTheApi(invoiceQuery("i-1").queryKey)).toBe(false);
    expect(isAboutTheApi(invoicesQuery.queryKey)).toBe(false);
  });

  it("keep each invoice under a key of its own", () => {
    expect(invoiceQuery("i-1").queryKey).not.toEqual(
      invoiceQuery("i-2").queryKey,
    );
  });
});

describe("The explanations of a stored invoice", () => {
  it("are kept under the invoice's key, one entry for each language", () => {
    const invoice = invoiceQuery("i-1").queryKey;
    const serbian = explanationsQuery("i-1", "sr").queryKey;

    expect(serbian.slice(0, invoice.length)).toEqual(invoice);
    expect(serbian).not.toEqual(explanationsQuery("i-1", "en").queryKey);
    expect(isAboutTheApi(serbian)).toBe(false);
  });

  it("are never asked for again by themselves, since each costs the model's requests", () => {
    const { staleTime, gcTime, retry } = explanationsQuery("i-1", "sr");

    // Never stale, so neither a new page nor the window's focus asks again; kept when the page
    // is left; and a failure waits for the visitor to try again.
    expect({ staleTime, gcTime, retry }).toEqual({
      staleTime: Infinity,
      gcTime: Infinity,
      retry: false,
    });
  });
});

describe("The repairs of a stored invoice", () => {
  it("are kept under the invoice's key, each repair under one of its own", () => {
    const invoice = invoiceQuery("i-1").queryKey;
    const repair = repairQuery("i-1", "r-1").queryKey;

    expect(repair.slice(0, invoice.length)).toEqual(invoice);
    expect(repair).not.toEqual(repairQuery("i-1", "r-2").queryKey);
    expect(isAboutTheApi(repair)).toBe(false);
  });

  it("are listed under the invoice's key, apart from each repair", () => {
    const invoice = invoiceQuery("i-1").queryKey;
    const list = repairsQuery("i-1").queryKey;

    expect(list.slice(0, invoice.length)).toEqual(invoice);
    expect(repairQuery("i-1", "r-1").queryKey).not.toEqual(list);
  });
});
