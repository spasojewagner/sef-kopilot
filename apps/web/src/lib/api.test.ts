import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  apiUrl,
  getHealth,
  request,
  REQUEST_TIMEOUT_MS,
} from "./api";

const HEALTH = { status: "ok", service: "sef-kopilot-api", version: "0.2.0" };

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Answers every request with ``respond``, and records what was asked. */
function stubFetch(
  respond: (init: RequestInit) => Response | Promise<Response>,
) {
  const fetch = vi.fn(
    async (input: RequestInfo | URL, init: RequestInit = {}) => respond(init),
  );
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

/** A request the API never answers: it ends only when its signal aborts it. */
function silence(init: RequestInit): Promise<Response> {
  return new Promise((_, reject) => {
    const signal = init.signal;
    if (signal?.aborted) {
      reject(signal.reason);
    }
    signal?.addEventListener("abort", () => reject(signal.reason));
  });
}

describe("The API's address", () => {
  it("is the build's NEXT_PUBLIC_API_URL, without a trailing slash", () => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", "https://api.example/");

    expect(apiUrl("/health")).toBe("https://api.example/health");
  });

  it("is uvicorn's on this machine when the build names none", () => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", undefined);

    expect(apiUrl("/health")).toBe("http://127.0.0.1:8000/health");
  });
});

describe("A request to the API", () => {
  beforeEach(() => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", "https://api.example");
  });

  it("asks for JSON and gives the answer", async () => {
    const fetch = stubFetch(() => json(200, HEALTH));

    await expect(getHealth()).resolves.toEqual(HEALTH);

    const [url, init] = fetch.mock.calls[0];
    expect(url).toBe("https://api.example/health");
    expect(new Headers(init?.headers).get("Accept")).toBe("application/json");
  });

  it("sends the headers it is given", async () => {
    const fetch = stubFetch(() => json(200, {}));

    await request("/auth/me", { headers: { Authorization: "Bearer token" } });

    const headers = new Headers(fetch.mock.calls[0][1]?.headers);
    expect(headers.get("Authorization")).toBe("Bearer token");
    expect(headers.get("Accept")).toBe("application/json");
  });

  it("throws the reason the API gave for an error", async () => {
    stubFetch(() => json(409, { detail: "the invoice changed meanwhile" }));

    const error = await request("/invoices/1").catch(
      (thrown: unknown) => thrown,
    );

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 409,
      detail: "the invoice changed meanwhile",
    });
  });

  it("joins the problems of a request the API could not read", async () => {
    stubFetch(() =>
      json(422, {
        detail: [
          {
            loc: ["body", "email"],
            msg: "value is not a valid email",
            type: "value_error",
          },
          { loc: ["body", "password"], msg: "Field required", type: "missing" },
        ],
      }),
    );

    await expect(request("/auth/register")).rejects.toMatchObject({
      status: 422,
      detail: "value is not a valid email; Field required",
    });
  });

  it("names the status when an error gives no reason", async () => {
    stubFetch(
      () =>
        new Response("<h1>Bad gateway</h1>", {
          status: 502,
          statusText: "Bad Gateway",
        }),
    );
    await expect(request("/health")).rejects.toMatchObject({
      status: 502,
      detail: "Bad Gateway",
    });

    stubFetch(() => new Response(null, { status: 503 }));
    await expect(request("/health")).rejects.toMatchObject({
      status: 503,
      detail: "HTTP 503",
    });
  });

  it("keeps an error's body, and the seconds Retry-After asks to wait", async () => {
    stubFetch(
      () =>
        new Response(JSON.stringify({ detail: "too many requests" }), {
          status: 429,
          headers: { "Content-Type": "application/json", "Retry-After": "42" },
        }),
    );
    await expect(request("/auth/login")).rejects.toMatchObject({
      status: 429,
      body: { detail: "too many requests" },
      retryAfter: 42,
    });

    stubFetch(
      () =>
        new Response(null, {
          status: 503,
          headers: { "Retry-After": "Fri, 06 Nov 2026 18:00:00 GMT" },
        }),
    );
    await expect(request("/health")).rejects.toMatchObject({
      body: null,
      retryAfter: null,
    });
  });

  it("reads no body from an answer that has none", async () => {
    stubFetch(() => new Response(null, { status: 204 }));

    await expect(request("/auth/logout")).resolves.toBeUndefined();
  });

  it("lets the browser's error through when the API cannot be reached", async () => {
    stubFetch(() => Promise.reject(new TypeError("Failed to fetch")));

    const error = await request("/health").catch((thrown: unknown) => thrown);

    expect(error).toBeInstanceOf(TypeError);
    expect(error).not.toBeInstanceOf(ApiError);
  });

  it("gives up when the API does not answer in time", async () => {
    vi.useFakeTimers();
    try {
      stubFetch(silence);

      const asked = request("/health").catch((thrown: unknown) => thrown);
      await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS);

      expect(await asked).toMatchObject({ name: "TimeoutError" });
    } finally {
      vi.useRealTimers();
    }
  });

  it("stops when the caller cancels, sooner or before it starts", async () => {
    stubFetch(silence);
    const leaving = new AbortController();

    const asked = request("/health", { signal: leaving.signal }).catch(
      (thrown: unknown) => thrown,
    );
    leaving.abort(new DOMException("the page was left", "AbortError"));
    expect(await asked).toMatchObject({ name: "AbortError" });

    await expect(
      request("/health", { signal: leaving.signal }),
    ).rejects.toMatchObject({ name: "AbortError" });
  });

  it("leaves no timer behind once it is answered", async () => {
    vi.useFakeTimers();
    try {
      stubFetch(() => json(200, HEALTH));

      await getHealth();

      expect(vi.getTimerCount()).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });
});
