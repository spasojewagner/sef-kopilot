import { describe, expect, it } from "vitest";

import { securityHeaders } from "./security-headers";

const policyOf = (headers: { key: string; value: string }[]) =>
  Object.fromEntries(
    (headers.find(({ key }) => key === "Content-Security-Policy")?.value ?? "")
      .split("; ")
      .map((directive) => {
        const [name, ...sources] = directive.split(" ");
        return [name, sources];
      }),
  );

describe("The headers every page is served with", () => {
  it("let a page reach its own site and the API alone, and be framed by none", () => {
    const policy = policyOf(securityHeaders("https://api.example/v1/", false));

    expect(policy["connect-src"]).toEqual(["'self'", "https://api.example"]);
    expect(policy["default-src"]).toEqual(["'self'"]);
    expect(policy["img-src"]).toEqual(["'self'", "data:", "blob:"]);
    expect(policy["object-src"]).toEqual(["blob:"]);
    expect(policy["frame-ancestors"]).toEqual(["'none'"]);
    expect(policy["form-action"]).toEqual(["'self'"]);
    expect(policy["script-src"]).not.toContain("'unsafe-eval'");
  });

  it("allow evaluated scripts in development alone, which its refreshing needs", () => {
    expect(
      policyOf(securityHeaders("http://127.0.0.1:8000", true))["script-src"],
    ).toContain("'unsafe-eval'");
  });

  it("send no address on, and refuse to be sniffed, framed or given a device", () => {
    const headers = Object.fromEntries(
      securityHeaders("https://api.example", false).map(({ key, value }) => [
        key,
        value,
      ]),
    );

    expect(headers["Referrer-Policy"]).toBe("no-referrer");
    expect(headers["X-Content-Type-Options"]).toBe("nosniff");
    expect(headers["X-Frame-Options"]).toBe("DENY");
    expect(headers["Permissions-Policy"]).toContain("camera=()");
  });
});
