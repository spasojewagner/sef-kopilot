import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import { healthQuery, isAboutTheApi, meQuery } from "./queries";

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
  });
});
