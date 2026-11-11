import { defineConfig } from "@playwright/test";

import e2e from "./playwright.config";

/**
 * The README's demo: the golden path recorded in Chromium (`demo/golden-path.demo.ts`), against
 * the end-to-end test's API and build, which the test's configuration starts on ports of their
 * own, the API with a scripted model (ADR-0033). It records rather than tests, and is not run in
 * CI; `make demo-gif` runs it and makes the GIF of its frames:
 *
 *     pnpm --filter @sef-kopilot/web demo
 */
export default defineConfig({
  ...e2e,
  testDir: "./demo",
  testMatch: "*.demo.ts",
  reporter: [["list"]],
  use: { ...e2e.use, trace: "off", screenshot: "off" },
});
