import { describe, expect, it, vi } from "vitest";

import { siteUrl } from "./links";

describe("The site's address", () => {
  it("is SITE_URL, when it is set", () => {
    vi.stubEnv("SITE_URL", "https://sef-kopilot.example");

    expect(siteUrl()?.href).toBe("https://sef-kopilot.example/");
  });

  it("is left to Next.js when it is not", () => {
    vi.stubEnv("SITE_URL", "");

    expect(siteUrl()).toBeUndefined();
  });
});
