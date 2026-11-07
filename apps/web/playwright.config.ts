import { defineConfig, devices } from "@playwright/test";

/**
 * The end-to-end smoke test (ADR-0033): the golden path in Chromium, against the web
 * application's production build and the API, which starts on a database of its own with a
 * scripted language model (`scripts/serve_e2e_api.py`). Both are started for the test and
 * stopped after it, on ports of their own, so that they run beside `make api` and `pnpm dev`.
 *
 * Run it with `pnpm --filter @sef-kopilot/web e2e` (or `make e2e`), once PostgreSQL is up and
 * `SEF_TEST_DATABASE_URL` names it, and the rule sets are fetched.
 */

const API = "http://127.0.0.1:8100";
const WEB = "http://localhost:3100";

export default defineConfig({
  testDir: "./e2e",
  // One test, in one browser. A smoke test that fails is a fault to find in its trace, not a
  // run to try again: nothing is retried.
  workers: 1,
  retries: 0,
  forbidOnly: Boolean(process.env.CI),
  // An upload, a repair and an approval each validate the invoice in the API.
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: [
    ...(process.env.CI ? [["github"] as const] : []),
    ["list"],
    ["html", { open: "never" }],
  ],
  use: {
    baseURL: WEB,
    // A press waits for what it presses as long as a check waits for what it reads.
    actionTimeout: 15_000,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      name: "api",
      command: `uv run python scripts/serve_e2e_api.py --port 8100 --web-origin ${WEB}`,
      cwd: "../..",
      // Ready once /ready answers 200: its database answers and its rule sets are compiled.
      url: `${API}/ready`,
      timeout: 180_000,
      reuseExistingServer: false,
      gracefulShutdown: { signal: "SIGINT", timeout: 10_000 },
    },
    {
      name: "web",
      // The build writes the API's address into the code the browser loads.
      command: "pnpm build && pnpm start --port 3100",
      env: { NEXT_PUBLIC_API_URL: API, NEXT_TELEMETRY_DISABLED: "1" },
      url: WEB,
      timeout: 300_000,
      reuseExistingServer: false,
    },
  ],
});
