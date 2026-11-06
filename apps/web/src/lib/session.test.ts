import { beforeEach, describe, expect, it, vi } from "vitest";

type SessionModule = typeof import("./session");

const ALICE = {
  user: { id: "u-alice", email: "alice@primer.example" },
  organization: { id: "o-primer", name: "Primer d.o.o." },
  role: "owner",
};
const BOB = {
  user: { id: "u-bob", email: "bob@primer.example" },
  organization: { id: "o-primer", name: "Primer d.o.o." },
  role: "client",
};

function tokens(
  access: string,
  refresh: string,
  {
    who = ALICE,
    expiresIn = 900,
  }: { who?: typeof ALICE; expiresIn?: number } = {},
) {
  return {
    token_type: "bearer",
    access_token: access,
    expires_in: expiresIn,
    refresh_token: refresh,
    refresh_expires_in: 30 * 24 * 3600,
    ...who,
  };
}

function json(status: number, body: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

interface Call {
  path: string;
  authorization: string | null;
  body: Record<string, unknown> | null;
}

/** Answers each request with ``answer(call)``; ``calls`` records what the API was asked. */
function stubApi(answer: (call: Call) => Response | Promise<Response>) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const call: Call = {
        path: new URL(String(input)).pathname,
        authorization: new Headers(init.headers).get("Authorization"),
        body: typeof init.body === "string" ? JSON.parse(init.body) : null,
      };
      calls.push(call);
      return answer(call);
    }),
  );
  return calls;
}

function keep(
  refreshToken: string,
  who = ALICE,
  expiresAt = Date.now() + 3_600_000,
) {
  localStorage.setItem(
    "sef-kopilot.session",
    JSON.stringify({
      refreshToken,
      refreshExpiresAt: expiresAt,
      identity: who,
    }),
  );
}

function kept(): { refreshToken: string; identity: typeof ALICE } | null {
  const raw = localStorage.getItem("sef-kopilot.session");
  return raw === null ? null : JSON.parse(raw);
}

/** Another tab wrote the session: this tab hears of it as the browser tells it. */
function anotherTabWrote(): void {
  window.dispatchEvent(
    new StorageEvent("storage", {
      key: "sef-kopilot.session",
      newValue: localStorage.getItem("sef-kopilot.session"),
    }),
  );
}

let session: SessionModule;

beforeEach(async () => {
  localStorage.clear();
  vi.resetModules();
  session = await import("./session");
});

describe("Signing in", () => {
  it("keeps the refresh token and whose it is, and the access token in memory only", async () => {
    stubApi(() => json(200, tokens("access-1", "refresh-1")));

    await session.signIn({
      email: "alice@primer.example",
      password: "a long passphrase",
    });

    expect(kept()).toMatchObject({
      refreshToken: "refresh-1",
      identity: ALICE,
    });
    expect(localStorage.getItem("sef-kopilot.session")).not.toContain(
      "access-1",
    );
    expect(session.currentSession()).toEqual({
      status: "signed-in",
      identity: ALICE,
    });
  });

  it("lists the organizations to choose from when the API asks for one", async () => {
    const organizations = [
      { organization: { id: "o-1", name: "Prva" }, role: "owner" },
      { organization: { id: "o-2", name: "Druga" }, role: "client" },
    ];
    const calls = stubApi(({ body }) =>
      body?.organization_id === "o-2"
        ? json(200, tokens("access-2", "refresh-2"))
        : json(409, { detail: "choose an organization", organizations }),
    );

    const error = await session
      .signIn({ email: "alice@primer.example", password: "a long passphrase" })
      .catch((thrown: unknown) => thrown);
    expect(session.organizationsToChoose(error)).toEqual(organizations);

    await session.signIn({
      email: "alice@primer.example",
      password: "a long passphrase",
      organizationId: "o-2",
    });
    expect(calls.map((call) => call.body?.organization_id)).toEqual([
      null,
      "o-2",
    ]);
    expect(session.organizationsToChoose(new Error("no"))).toBeNull();
  });

  it("registers an account with its organization, and signs in", async () => {
    const calls = stubApi(() => json(201, tokens("access-1", "refresh-1")));

    const who = await session.register({
      email: "alice@primer.example",
      password: "a long passphrase",
      organizationName: "Primer d.o.o.",
    });

    expect(who).toEqual(ALICE);
    expect(calls[0]).toMatchObject({
      path: "/auth/register",
      body: {
        email: "alice@primer.example",
        organization_name: "Primer d.o.o.",
      },
    });
  });
});

describe("A request in the visitor's name", () => {
  it("carries the access token", async () => {
    const calls = stubApi(({ path }) =>
      path === "/auth/login"
        ? json(200, tokens("access-1", "refresh-1"))
        : json(200, {}),
    );
    await session.signIn({
      email: "alice@primer.example",
      password: "a long passphrase",
    });

    await session.authorized("/auth/me");

    expect(calls.map((call) => [call.path, call.authorization])).toEqual([
      ["/auth/login", null],
      ["/auth/me", "Bearer access-1"],
    ]);
  });

  it("is sent after a refresh when the access token is about to expire", async () => {
    const calls = stubApi(({ path }) => {
      if (path === "/auth/login") {
        return json(200, tokens("access-1", "refresh-1", { expiresIn: 20 }));
      }
      return path === "/auth/refresh"
        ? json(200, tokens("access-2", "refresh-2"))
        : json(200, {});
    });
    await session.signIn({
      email: "alice@primer.example",
      password: "a long passphrase",
    });

    await session.authorized("/auth/me");

    expect(calls.slice(1)).toEqual([
      {
        path: "/auth/refresh",
        authorization: null,
        body: { refresh_token: "refresh-1" },
      },
      { path: "/auth/me", authorization: "Bearer access-2", body: null },
    ]);
    expect(kept()?.refreshToken).toBe("refresh-2");
  });

  it("refreshes first after a reload, with the token kept", async () => {
    keep("refresh-1");
    const calls = stubApi(({ path }) =>
      path === "/auth/refresh"
        ? json(200, tokens("access-2", "refresh-2"))
        : json(200, {}),
    );

    expect(session.currentSession()).toEqual({
      status: "signed-in",
      identity: ALICE,
    });
    await session.authorized("/auth/me");

    expect(calls.map((call) => call.path)).toEqual([
      "/auth/refresh",
      "/auth/me",
    ]);
  });

  it("shares one refresh with the requests sent at the same moment", async () => {
    keep("refresh-1");
    const calls = stubApi(({ path }) =>
      path === "/auth/refresh"
        ? json(200, tokens("access-2", "refresh-2"))
        : json(200, {}),
    );

    await Promise.all([
      session.authorized("/invoices"),
      session.authorized("/auth/me"),
    ]);

    expect(calls.filter((call) => call.path === "/auth/refresh")).toHaveLength(
      1,
    );
  });

  it("is sent once more with a new token when the API refuses the one it had", async () => {
    keep("refresh-1");
    let refreshes = 0;
    const calls = stubApi(({ path, authorization }) => {
      if (path === "/auth/refresh") {
        refreshes += 1;
        return json(
          200,
          tokens(`access-${refreshes + 1}`, `refresh-${refreshes + 1}`),
        );
      }
      return authorization === "Bearer access-2"
        ? json(401, { detail: "the token has expired" })
        : json(200, { ok: true });
    });

    await expect(session.authorized("/auth/me")).resolves.toEqual({ ok: true });

    expect(calls.map((call) => [call.path, call.authorization])).toEqual([
      ["/auth/refresh", null],
      ["/auth/me", "Bearer access-2"],
      ["/auth/refresh", null],
      ["/auth/me", "Bearer access-3"],
    ]);
  });

  it("ends the session when the API refuses the refresh token", async () => {
    keep("refresh-1");
    stubApi(() => json(401, { detail: "the refresh token is not valid" }));

    const error = await session
      .authorized("/auth/me")
      .catch((thrown: unknown) => thrown);

    expect(error).toBeInstanceOf(session.SignedOutError);
    expect(kept()).toBeNull();
    expect(session.currentSession()).toEqual({ status: "signed-out" });
  });

  it("keeps the session when the API cannot be reached", async () => {
    keep("refresh-1");
    stubApi(() => Promise.reject(new TypeError("Failed to fetch")));

    await expect(session.authorized("/auth/me")).rejects.toBeInstanceOf(
      TypeError,
    );

    expect(kept()?.refreshToken).toBe("refresh-1");
  });

  it("is not sent when nobody is signed in", async () => {
    const calls = stubApi(() => json(200, {}));

    await expect(session.authorized("/auth/me")).rejects.toBeInstanceOf(
      session.SignedOutError,
    );

    expect(calls).toEqual([]);
  });

  it("is not sent when the session has expired, which is forgotten", async () => {
    keep("refresh-1", ALICE, Date.now() - 1000);
    const calls = stubApi(() => json(200, {}));

    expect(session.currentSession()).toEqual({ status: "signed-out" });
    await expect(session.authorized("/auth/me")).rejects.toBeInstanceOf(
      session.SignedOutError,
    );

    expect(calls).toEqual([]);
    expect(kept()).toBeNull();
  });
});

describe("The browser's tabs", () => {
  it("take turns to refresh, each spending the token kept last", async () => {
    keep("refresh-1");
    const request = vi.fn(
      async (name: string, work: () => Promise<unknown>) => {
        // While this tab waited for its turn, another one spent the token and kept the next.
        keep("refresh-from-another-tab");
        return work();
      },
    );
    vi.stubGlobal("navigator", { ...navigator, locks: { request } });
    const calls = stubApi(({ path }) =>
      path === "/auth/refresh"
        ? json(200, tokens("access-2", "refresh-2"))
        : json(200, {}),
    );

    await session.authorized("/auth/me");

    expect(request).toHaveBeenCalledWith(
      session.REFRESH_LOCK,
      expect.any(Function),
    );
    expect(calls[0].body).toEqual({
      refresh_token: "refresh-from-another-tab",
    });
  });

  it("hear that another one signed out, and forget the access token", async () => {
    stubApi(({ path }) =>
      path === "/auth/login"
        ? json(200, tokens("access-1", "refresh-1"))
        : json(200, {}),
    );
    await session.signIn({
      email: "alice@primer.example",
      password: "a long passphrase",
    });
    const listener = vi.fn();
    const unsubscribe = session.subscribe(listener);

    localStorage.removeItem("sef-kopilot.session");
    anotherTabWrote();

    expect(listener).toHaveBeenCalled();
    expect(session.currentSession()).toEqual({ status: "signed-out" });
    await expect(session.authorized("/auth/me")).rejects.toBeInstanceOf(
      session.SignedOutError,
    );
    unsubscribe();
  });

  it("keep their access tokens when another one refreshes for the same visitor", async () => {
    const calls = stubApi(({ path }) =>
      path === "/auth/login"
        ? json(200, tokens("access-1", "refresh-1"))
        : json(200, {}),
    );
    await session.signIn({
      email: "alice@primer.example",
      password: "a long passphrase",
    });
    const unsubscribe = session.subscribe(() => {});

    keep("refresh-2");
    anotherTabWrote();
    await session.authorized("/auth/me");

    expect(calls.at(-1)).toMatchObject({
      path: "/auth/me",
      authorization: "Bearer access-1",
    });
    unsubscribe();
  });

  it("drop their access tokens when another visitor signs in in another one", async () => {
    const calls = stubApi(({ path }) => {
      if (path === "/auth/login") {
        return json(200, tokens("access-alice", "refresh-alice"));
      }
      return path === "/auth/refresh"
        ? json(200, tokens("access-bob", "refresh-bob2", { who: BOB }))
        : json(200, {});
    });
    await session.signIn({
      email: "alice@primer.example",
      password: "a long passphrase",
    });
    const unsubscribe = session.subscribe(() => {});

    keep("refresh-bob", BOB);
    anotherTabWrote();
    await session.authorized("/auth/me");

    expect(session.currentSession()).toEqual({
      status: "signed-in",
      identity: BOB,
    });
    expect(calls.at(-1)).toMatchObject({
      path: "/auth/me",
      authorization: "Bearer access-bob",
    });
    unsubscribe();
  });
});

describe("Signing out", () => {
  it("forgets the session at once, then has the API revoke it", async () => {
    const calls = stubApi(({ path }) =>
      path === "/auth/login"
        ? json(200, tokens("access-1", "refresh-1"))
        : json(204, undefined),
    );
    await session.signIn({
      email: "alice@primer.example",
      password: "a long passphrase",
    });

    const leaving = session.signOut();
    expect(kept()).toBeNull();
    expect(session.currentSession()).toEqual({ status: "signed-out" });
    await leaving;

    expect(calls.at(-1)).toEqual({
      path: "/auth/logout",
      authorization: null,
      body: { refresh_token: "refresh-1" },
    });
    await expect(session.authorized("/auth/me")).rejects.toBeInstanceOf(
      session.SignedOutError,
    );
  });

  it("forgets the session when the API cannot be reached", async () => {
    keep("refresh-1");
    stubApi(() => Promise.reject(new TypeError("Failed to fetch")));

    await expect(session.signOut()).resolves.toBeUndefined();

    expect(kept()).toBeNull();
  });
});

describe("Without local storage", () => {
  it("keeps the session in the tab's memory", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("refused", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("refused", "SecurityError");
    });
    const calls = stubApi(({ path }) =>
      path === "/auth/login"
        ? json(200, tokens("access-1", "refresh-1"))
        : json(200, {}),
    );

    await session.signIn({
      email: "alice@primer.example",
      password: "a long passphrase",
    });
    await session.authorized("/auth/me");

    expect(session.currentSession()).toEqual({
      status: "signed-in",
      identity: ALICE,
    });
    expect(calls.at(-1)?.authorization).toBe("Bearer access-1");
    vi.restoreAllMocks();
  });
});

describe("The session as a page reads it", () => {
  it("is the same object until it changes", async () => {
    keep("refresh-1");

    const first = session.currentSession();

    expect(session.currentSession()).toBe(first);
    expect(session.serverSession()).toEqual({ status: "unknown" });
  });
});
