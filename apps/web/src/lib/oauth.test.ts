import { describe, expect, it } from "vitest";

import { json, keepSession, stubApi } from "@/test/api";

import {
  approveAuthorizationRequest,
  destinationOf,
  getAuthorizationRequest,
  publisherOf,
  refuseAuthorizationRequest,
} from "./oauth";

describe("A client's redirect URI", () => {
  it.each([
    ["https://claude.ai/api/mcp/auth_callback", "claude.ai", false],
    ["https://chatgpt.com:8443/connector/oauth/x", "chatgpt.com:8443", false],
    ["http://127.0.0.1:6274/oauth/callback", "127.0.0.1:6274", true],
    ["http://localhost:33418/callback", "localhost:33418", true],
    ["http://[::1]:5000/cb", "[::1]:5000", true],
    [
      "cursor://anysphere.cursor-mcp/oauth/callback",
      "cursor://anysphere.cursor-mcp",
      true,
    ],
    ["com.example.app:/oauth2redirect", "com.example.app:", true],
  ])("%s takes the person to %s", (uri, address, local) => {
    expect(destinationOf(uri)).toEqual({ address, local });
  });

  it("is shown whole when it cannot be read as an address", () => {
    expect(destinationOf("not an address")).toEqual({
      address: "not an address",
      local: false,
    });
  });
});

describe("A request", () => {
  it("is read, approved and refused in the visitor's name, by its id", async () => {
    keepSession();
    const asked = stubApi(() =>
      json(200, { redirect_uri: "https://x.example" }),
    );

    await getAuthorizationRequest("a/b");
    await approveAuthorizationRequest("a/b");
    await refuseAuthorizationRequest("a/b");

    expect(asked.map(({ method, path }) => `${method} ${path}`)).toEqual([
      "GET /oauth/requests/a%2Fb",
      "POST /oauth/requests/a%2Fb/approval",
      "POST /oauth/requests/a%2Fb/refusal",
    ]);
    expect(asked[1].headers.get("Authorization")).toBe("Bearer access-2");
  });
});

describe("A client's identifier", () => {
  it.each([
    // A client known by its metadata document: the host that published it.
    ["https://claude.ai/oauth/mcp-client.json", "claude.ai"],
    ["https://tools.example:8443/client.json", "tools.example:8443"],
    // A registered client, whose identifier the server made up.
    ["tdAz3_q9k1Q2e7Yb0xWv5n8LmC4", null],
    ["http://assistant.example/client.json", null],
    ["https://", null],
  ])("%j is published by %j", (clientId, publisher) => {
    expect(publisherOf(clientId)).toBe(publisher);
  });
});
