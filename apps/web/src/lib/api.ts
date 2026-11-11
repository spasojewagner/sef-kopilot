import type { components } from "@/lib/api-schema";

/**
 * The browser's way to the API: the address it answers at, one request function, which waits
 * while a sleeping API wakes, and the error it throws when the API answers with an error.
 *
 * The pages call the API directly, across origins (ADR-0026); the API allows it for the origins
 * in its `SEF_WEB_ORIGINS`.
 */

/** Where the API answers when the build names no other address: `uvicorn`'s default. */
const LOCAL_API_URL = "http://127.0.0.1:8000";

/** How long a request may take, its answer read, before it is abandoned, unless it says. */
export const REQUEST_TIMEOUT_MS = 10_000;

/**
 * A request; how long it may take when that is not {@link REQUEST_TIMEOUT_MS}; whether it
 * waits first while a sleeping API wakes (`wake`, by default), as every request of a page does;
 * and whether its answer is read as text (`text`), an XML document say, rather than as JSON.
 */
export type ApiRequest = RequestInit & {
  timeoutMs?: number;
  wake?: boolean;
  text?: boolean;
};

/** The address of `path` on the API, as the build was given it in `NEXT_PUBLIC_API_URL`. */
export function apiUrl(path: string): string {
  // Next.js writes the variable's value into the code when the application is built.
  const base = process.env.NEXT_PUBLIC_API_URL || LOCAL_API_URL;
  return `${base.replace(/\/+$/, "")}${path}`;
}

/**
 * The API answered, but with an error: its status, the reason it gave, the whole body for an
 * error that says more (the organizations to choose from, say), and for a 429 the seconds to
 * wait before trying again.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  readonly body: unknown;
  readonly retryAfter: number | null;

  constructor(
    status: number,
    detail: string,
    {
      body = null,
      retryAfter = null,
    }: { body?: unknown; retryAfter?: number | null } = {},
  ) {
    super(`The API answered ${status}: ${detail}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.body = body;
    this.retryAfter = retryAfter;
  }
}

/** The seconds of a `Retry-After` header, which the API gives as a whole number. */
function secondsOf(header: string | null): number | null {
  if (header === null || !/^\d+$/.test(header.trim())) {
    return null;
  }
  return Number(header.trim());
}

/**
 * The reason in an error's body: the API's `detail`, which is a text, or for a request it could
 * not read a list of problems, each with its `msg`.
 */
function reasonOf(body: unknown): string | null {
  if (typeof body !== "object" || body === null || !("detail" in body)) {
    return null;
  }
  const { detail } = body;
  if (typeof detail === "string") {
    return detail;
  }
  if (!Array.isArray(detail)) {
    return null;
  }
  const messages = detail.flatMap((problem: unknown) =>
    typeof problem === "object" &&
    problem !== null &&
    "msg" in problem &&
    typeof problem.msg === "string"
      ? [problem.msg]
      : [],
  );
  return messages.length > 0 ? messages.join("; ") : null;
}

async function bodyOf(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

/**
 * The API's JSON answer to a request for `path`, or nothing for a 204.
 *
 * When the API has not answered for a while, the request waits until it does: see
 * {@link whenAwake}. It is then sent once, and its `timeoutMs` counts from there.
 *
 * Throws an {@link ApiError} when the API answers with an error, and the browser's own error
 * when it cannot reach the API, may not read its answer, or gives up after `timeoutMs`
 * ({@link REQUEST_TIMEOUT_MS} unless it says). `signal` cancels the request sooner.
 */
export async function request<T>(
  path: string,
  {
    signal,
    headers,
    timeoutMs = REQUEST_TIMEOUT_MS,
    wake = true,
    text = false,
    ...init
  }: ApiRequest = {},
): Promise<T> {
  if (wake) {
    await whenAwake(signal);
  }
  // A controller of its own rather than AbortSignal.any, which Safari has only since 17.4.
  const controller = new AbortController();
  const cancel = () => controller.abort(signal?.reason);
  const timer = setTimeout(() => {
    const reason = `no answer in ${timeoutMs} ms`;
    controller.abort(new DOMException(reason, "TimeoutError"));
  }, timeoutMs);
  if (signal?.aborted) {
    cancel();
  } else {
    signal?.addEventListener("abort", cancel, { once: true });
  }
  try {
    const sent = new Headers(headers);
    if (!sent.has("Accept")) {
      sent.set("Accept", "application/json");
    }
    const response = await fetch(apiUrl(path), {
      ...init,
      headers: sent,
      signal: controller.signal,
    });
    if (response.status < 500) {
      // An answer below 500 comes from the API itself, which is then awake; a 5xx may be its
      // platform's, while it starts.
      noteAnswer();
    }
    if (!response.ok) {
      const body = await bodyOf(response);
      throw new ApiError(
        response.status,
        reasonOf(body) ?? (response.statusText || `HTTP ${response.status}`),
        { body, retryAfter: secondsOf(response.headers.get("Retry-After")) },
      );
    }
    if (response.status === 204) {
      // No content: a sign-out, a deletion.
      return undefined as T;
    }
    if (text) {
      return (await response.text()) as T;
    }
    return (await response.json()) as T;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", cancel);
  }
}

/** The answers the API describes in its OpenAPI document, by their names there. */
export type Schemas = components["schemas"];

/** `GET /health`: the API's process is up, and which version it runs. */
export type Health = Schemas["HealthResponse"];

/**
 * Whether the API answers now, and which version it runs: one request while the API is taken to
 * be awake; otherwise the API may be asleep, and this waits for it as {@link whenAwake} does.
 */
export function getHealth(signal?: AbortSignal): Promise<Health> {
  if (knownToBeAwake()) {
    return request<Health>("/health", { signal, wake: false });
  }
  return untilSettled(wakeUp(), signal);
}

/*
 * A sleeping API (ADR-0036). The public demo's API runs on a free instance, which sleeps after
 * 15 minutes without a request and takes about a minute to wake, while its platform holds or
 * fails the requests. A request that gave up after 10 s would tell the visitor that the API does
 * not answer. So when the API has not answered for a while, a request first waits until it
 * answers `/health`, asked again for up to two minutes, and is sent only then: once, so that no
 * write is ever sent twice.
 */

/** How the browser waits for a sleeping API. */
export const WAKE = {
  /**
   * The API is taken to be awake this long after its last answer: less than the 15 minutes
   * after which the free instance sleeps.
   */
  awakeForMs: 10 * 60_000,
  /** How long a sleeping API may take to answer before it is taken to be down. */
  withinMs: 120_000,
  /** How long a wake-up may go unanswered before the pages say that the API is waking up. */
  wakingAfterMs: 3_000,
  /** How long one request to `/health` may take during a wake-up. */
  attemptMs: 30_000,
  /** The pause after a request to `/health` that failed, before the next. */
  pauseMs: 2_000,
} as const;

/** When the API last answered this tab, by `Date.now()`; never, when a visit begins. */
let answeredAt: number | null = null;
/** The wake-up under way, which every waiting request shares. */
let wakingUp: Promise<Health> | null = null;
/** Whether the wake-up under way has gone unanswered for {@link WAKE.wakingAfterMs}. */
let waking = false;
const wakingListeners = new Set<() => void>();

/** The API answered just now. */
export function noteAnswer(): void {
  answeredAt = Date.now();
}

/** Forgets that the API ever answered, as a new visit does: for the tests. */
export function forgetAnswers(): void {
  answeredAt = null;
  wakingUp = null;
  setWaking(false);
}

/** Whether the API answered recently enough to be taken to be awake. */
function knownToBeAwake(): boolean {
  return answeredAt !== null && Date.now() - answeredAt < WAKE.awakeForMs;
}

function setWaking(value: boolean): void {
  if (waking !== value) {
    waking = value;
    for (const listener of wakingListeners) {
      listener();
    }
  }
}

/** Whether the API is waking up: a wake-up has gone unanswered for a few seconds. */
export function isApiWaking(): boolean {
  return waking;
}

/** Calls ``listener`` each time {@link isApiWaking} changes; returns how to stop. */
export function subscribeToApiWaking(listener: () => void): () => void {
  wakingListeners.add(listener);
  return () => {
    wakingListeners.delete(listener);
  };
}

/**
 * Resolves at once while the API is taken to be awake, and in a page rendered on the server;
 * otherwise once the API answers `/health`, asked again until it does or {@link WAKE.withinMs}
 * have passed. Rejects with the last request's error when the API never answers, and with
 * ``signal``'s reason when it aborts, which ends this wait but not the wake-up, which the other
 * requests share.
 */
export async function whenAwake(signal?: AbortSignal | null): Promise<void> {
  if (typeof window === "undefined" || knownToBeAwake()) {
    return;
  }
  try {
    await untilSettled(wakeUp(), signal);
  } catch (error) {
    // A refusal is an answer: the API is awake, and the request may go.
    if (!(error instanceof ApiError && error.status < 500)) {
      throw error;
    }
  }
}

/** The wake-up under way, or a new one. */
function wakeUp(): Promise<Health> {
  if (wakingUp === null) {
    wakingUp = askUntilAwake().finally(() => {
      wakingUp = null;
    });
    // Each request that waits handles its failure; one that none waits for any more is no error.
    wakingUp.catch(() => undefined);
  }
  return wakingUp;
}

async function askUntilAwake(): Promise<Health> {
  const deadline = Date.now() + WAKE.withinMs;
  const slow = setTimeout(() => setWaking(true), WAKE.wakingAfterMs);
  try {
    for (;;) {
      try {
        return await request<Health>("/health", {
          wake: false,
          timeoutMs: Math.max(
            1,
            Math.min(WAKE.attemptMs, deadline - Date.now()),
          ),
        });
      } catch (error) {
        const refused = error instanceof ApiError && error.status < 500;
        if (refused || Date.now() + WAKE.pauseMs >= deadline) {
          throw error;
        }
      }
      await new Promise((resolve) => setTimeout(resolve, WAKE.pauseMs));
    }
  } finally {
    clearTimeout(slow);
    setWaking(false);
  }
}

/** ``promise``'s outcome, or ``signal``'s reason as soon as it aborts. */
function untilSettled<T>(
  promise: Promise<T>,
  signal?: AbortSignal | null,
): Promise<T> {
  if (!signal) {
    return promise;
  }
  if (signal.aborted) {
    return Promise.reject(signal.reason);
  }
  return new Promise<T>((resolve, reject) => {
    const abort = () => reject(signal.reason);
    signal.addEventListener("abort", abort, { once: true });
    promise
      .then(resolve, reject)
      .finally(() => signal.removeEventListener("abort", abort));
  });
}
