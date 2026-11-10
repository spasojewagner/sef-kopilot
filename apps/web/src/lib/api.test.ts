import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  apiUrl,
  forgetAnswers,
  getHealth,
  isApiWaking,
  noteAnswer,
  request,
  REQUEST_TIMEOUT_MS,
  subscribeToApiWaking,
  WAKE,
} from "./api";

const HEALTH = {
  status: "ok",
  service: "sef-kopilot-api",
  version: "0.2.0",
  public_demo: false,
};

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

  it("reads an answer as text when it is asked to, an XML document say", async () => {
    stubFetch(
      () =>
        new Response("<Invoice/>", {
          status: 200,
          headers: { "Content-Type": "application/xml" },
        }),
    );

    await expect(
      request<string>("/invoices/draft", { method: "POST", text: true }),
    ).resolves.toBe("<Invoice/>");
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

/** Answers each request by its path, and records the paths asked, in order. */
function stubPaths(
  answers: Record<string, (init: RequestInit) => Response | Promise<Response>>,
): string[] {
  const asked: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const path = new URL(String(input)).pathname;
      asked.push(path);
      const answer = answers[path];
      if (answer === undefined) {
        throw new TypeError(`no answer in a test: ${path}`);
      }
      return answer(init);
    }),
  );
  return asked;
}

/** An answer that comes ``ms`` after the request, unless its signal aborts it first. */
function after(ms: number, answer: () => Response) {
  return (init: RequestInit) =>
    new Promise<Response>((resolve, reject) => {
      const timer = setTimeout(() => resolve(answer()), ms);
      init.signal?.addEventListener("abort", () => {
        clearTimeout(timer);
        reject(init.signal?.reason);
      });
    });
}

/** A request that fails at once, as one does that its platform turns away. */
function turnedAway(): Promise<Response> {
  return Promise.reject(new TypeError("Failed to fetch"));
}

describe("A request while the API may be asleep", () => {
  beforeEach(() => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", "https://api.example");
    vi.useFakeTimers();
    return () => {
      vi.useRealTimers();
    };
  });

  it("is sent at once while the API answered less than ten minutes ago", async () => {
    noteAnswer();
    vi.advanceTimersByTime(WAKE.awakeForMs - 1);
    const asked = stubPaths({ "/invoices": () => json(200, []) });

    await request("/invoices");

    expect(asked).toEqual(["/invoices"]);
  });

  it("asks /health first when the API has not answered for ten minutes", async () => {
    noteAnswer();
    vi.advanceTimersByTime(WAKE.awakeForMs);
    const asked = stubPaths({
      "/health": () => json(200, HEALTH),
      "/invoices": () => json(200, []),
    });

    await request("/invoices");

    expect(asked).toEqual(["/health", "/invoices"]);
  });

  it("waits while a sleeping API wakes, and is then sent once", async () => {
    forgetAnswers();
    let wakeUps = 0;
    const asked = stubPaths({
      // The platform holds the first request until it gives up, and the API answers the next
      // one once it has started.
      "/health": (init) =>
        ++wakeUps === 1
          ? silence(init)
          : after(20_000, () => json(200, HEALTH))(init),
      "/invoices": () => json(200, []),
    });

    const sent = request("/invoices");
    await vi.advanceTimersByTimeAsync(WAKE.wakingAfterMs - 1);
    expect(isApiWaking()).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    expect(isApiWaking()).toBe(true);

    await vi.advanceTimersByTimeAsync(WAKE.attemptMs + WAKE.pauseMs);
    expect(asked).toEqual(["/health", "/health"]);
    await vi.advanceTimersByTimeAsync(20_000);

    await expect(sent).resolves.toEqual([]);
    expect(asked).toEqual(["/health", "/health", "/invoices"]);
    expect(isApiWaking()).toBe(false);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("is sent at once after the API has answered another request", async () => {
    forgetAnswers();
    const asked = stubPaths({
      "/health": () => json(200, HEALTH),
      "/invoices": () => json(200, []),
    });

    await request("/invoices");
    await request("/invoices");

    expect(asked).toEqual(["/health", "/invoices", "/invoices"]);
  });

  it("counts its own time from when it is sent, not from when it began to wait", async () => {
    forgetAnswers();
    stubPaths({
      "/health": after(15_000, () => json(200, HEALTH)),
      "/invoices": after(REQUEST_TIMEOUT_MS - 1, () => json(200, [])),
    });

    const sent = request("/invoices");
    await vi.advanceTimersByTimeAsync(15_000 + REQUEST_TIMEOUT_MS - 1);

    await expect(sent).resolves.toEqual([]);
  });

  it("gives up with the last error when the API does not answer within two minutes", async () => {
    forgetAnswers();
    const asked = stubPaths({
      "/health": turnedAway,
      "/invoices": () => json(200, []),
    });

    const sent = request("/invoices").catch((thrown: unknown) => thrown);
    await vi.advanceTimersByTimeAsync(WAKE.withinMs);

    expect(await sent).toBeInstanceOf(TypeError);
    expect(asked).not.toContain("/invoices");
    expect(asked.length).toBeGreaterThan(1);
    expect(isApiWaking()).toBe(false);
  });

  it("goes, if the API refuses /health: a refusal is an answer", async () => {
    forgetAnswers();
    const asked = stubPaths({
      "/health": () => json(404, { detail: "Not Found" }),
      "/invoices": () => json(200, []),
    });

    await expect(request("/invoices")).resolves.toEqual([]);
    expect(asked).toEqual(["/health", "/invoices"]);
  });

  it("shares one wake-up with the other requests that wait", async () => {
    forgetAnswers();
    const asked = stubPaths({
      "/health": after(10_000, () => json(200, HEALTH)),
      "/invoices": () => json(200, []),
      "/auth/me": () => json(200, {}),
    });

    const both = Promise.all([request("/invoices"), request("/auth/me")]);
    await vi.advanceTimersByTimeAsync(10_000);
    await both;

    expect(asked[0]).toBe("/health");
    expect(asked.slice(1).sort()).toEqual(["/auth/me", "/invoices"]);
  });

  it("stops waiting when its signal aborts, while the others wait on", async () => {
    forgetAnswers();
    const asked = stubPaths({
      "/health": after(10_000, () => json(200, HEALTH)),
      "/invoices": () => json(200, []),
      "/auth/me": () => json(200, {}),
    });
    const leaving = new AbortController();

    const left = request("/invoices", { signal: leaving.signal }).catch(
      (thrown: unknown) => thrown,
    );
    const stayed = request("/auth/me");
    await vi.advanceTimersByTimeAsync(5_000);
    leaving.abort(new DOMException("the page was left", "AbortError"));
    expect(await left).toMatchObject({ name: "AbortError" });
    await vi.advanceTimersByTimeAsync(5_000);

    await expect(stayed).resolves.toEqual({});
    expect(asked).toEqual(["/health", "/auth/me"]);
  });

  it("does not say that the API is waking up when it answers within a few seconds", async () => {
    forgetAnswers();
    stubPaths({
      "/health": after(WAKE.wakingAfterMs - 1, () => json(200, HEALTH)),
      "/invoices": () => json(200, []),
    });
    const told = vi.fn();
    const stop = subscribeToApiWaking(told);

    const sent = request("/invoices");
    await vi.advanceTimersByTimeAsync(WAKE.wakingAfterMs);
    await sent;
    stop();

    expect(told).not.toHaveBeenCalled();
  });
});

describe("The API's health", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    return () => {
      vi.useRealTimers();
    };
  });

  it("is one request while the API is taken to be awake", async () => {
    const asked = stubPaths({ "/health": turnedAway });

    await expect(getHealth()).rejects.toBeInstanceOf(TypeError);
    expect(asked).toEqual(["/health"]);
  });

  it("waits for a sleeping API, as a request does", async () => {
    forgetAnswers();
    let wakeUps = 0;
    stubPaths({
      "/health": () =>
        ++wakeUps < 3 ? turnedAway() : Promise.resolve(json(200, HEALTH)),
    });

    const health = getHealth();
    await vi.advanceTimersByTimeAsync(2 * WAKE.pauseMs);

    await expect(health).resolves.toEqual(HEALTH);
    expect(wakeUps).toBe(3);
  });
});
