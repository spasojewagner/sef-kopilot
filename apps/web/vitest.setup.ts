// Registers the jest-dom matchers (toBeInTheDocument, toHaveAttribute, ...) with Vitest's
// `expect`, and unmounts rendered trees between tests so they cannot leak into each other.
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

beforeEach(() => {
  // No test sees what another kept in the browser's storage: a signed-in session, say.
  localStorage.clear();
  // No test reaches the network: a request that a test does not answer itself fails, as if
  // the API could not be reached. Vitest puts the real fetch back after each test.
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) =>
      Promise.reject(new TypeError(`no answer in a test: ${String(input)}`)),
    ),
  );
});

afterEach(() => {
  cleanup();
});
