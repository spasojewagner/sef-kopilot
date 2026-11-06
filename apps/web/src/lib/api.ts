/**
 * The browser's way to the API: the address it answers at, one request function, and the
 * error it throws when the API answers with an error.
 *
 * The pages call the API directly, across origins (ADR-0026); the API allows it for the origins
 * in its `SEF_WEB_ORIGINS`.
 */

/** Where the API answers when the build names no other address: `uvicorn`'s default. */
const LOCAL_API_URL = "http://127.0.0.1:8000";

/** How long a request may take, its answer read, before it is abandoned. */
export const REQUEST_TIMEOUT_MS = 10_000;

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
 * Throws an {@link ApiError} when the API answers with an error, and the browser's own error
 * when it cannot reach the API, may not read its answer, or gives up after
 * {@link REQUEST_TIMEOUT_MS}. `signal` cancels the request sooner.
 */
export async function request<T>(
  path: string,
  { signal, headers, ...init }: RequestInit = {},
): Promise<T> {
  // A controller of its own rather than AbortSignal.any, which Safari has only since 17.4.
  const controller = new AbortController();
  const cancel = () => controller.abort(signal?.reason);
  const timer = setTimeout(() => {
    const reason = `no answer in ${REQUEST_TIMEOUT_MS} ms`;
    controller.abort(new DOMException(reason, "TimeoutError"));
  }, REQUEST_TIMEOUT_MS);
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
    return (await response.json()) as T;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", cancel);
  }
}

/** `GET /health`: the API's process is up, and which version it runs (`HealthResponse`). */
export interface Health {
  status: "ok";
  service: string;
  version: string;
}

export function getHealth(signal?: AbortSignal): Promise<Health> {
  return request<Health>("/health", { signal });
}
