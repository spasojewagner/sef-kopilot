import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { STORAGE_KEY } from "@/lib/session";
import { renderIn } from "@/test/render";

import { Account } from "./account";

const router = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
  prefetch: vi.fn(),
  back: vi.fn(),
  forward: vi.fn(),
  refresh: vi.fn(),
}));

vi.mock("next/navigation", async (importOriginal) => ({
  ...(await importOriginal<typeof import("next/navigation")>()),
  useRouter: () => router,
  usePathname: () => "/sr-Latn",
}));

const ALICE = {
  user: { id: "u-alice", email: "alice@primer.example" },
  organization: { id: "o-primer", name: "Primer d.o.o." },
  role: "owner",
};

/** The same visitor, with an address changed since this browser signed in. */
const ALICE_RENAMED = {
  ...ALICE,
  user: { id: "u-alice", email: "alice@novo.example" },
};

const TOKENS = {
  token_type: "bearer",
  access_token: "access-2",
  expires_in: 900,
  refresh_token: "refresh-2",
  refresh_expires_in: 2_592_000,
};

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function keepAlice() {
  localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({
      refreshToken: "refresh-1",
      refreshExpiresAt: Date.now() + 3_600_000,
      identity: ALICE,
    }),
  );
}

describe("Account in the header", () => {
  it("offers to sign in when nobody is signed in", () => {
    renderIn("sr-Latn", <Account />);

    expect(screen.getByRole("link", { name: "Prijava" })).toHaveAttribute(
      "href",
      "/sr-Latn/sign-in",
    );
  });

  it("shows who is signed in, as the API says, and signs out", async () => {
    keepAlice();
    const paths: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const path = new URL(String(input)).pathname;
        paths.push(path);
        if (path === "/auth/refresh") {
          return json(200, { ...TOKENS, ...ALICE_RENAMED });
        }
        return path === "/auth/me"
          ? json(200, ALICE_RENAMED)
          : new Response(null, { status: 204 });
      }),
    );
    router.push.mockClear();
    renderIn("sr-Latn", <Account />);

    expect(screen.getByText("alice@primer.example")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Fakture" })).toHaveAttribute(
      "href",
      "/sr-Latn/invoices",
    );
    expect(await screen.findByText("alice@novo.example")).toBeInTheDocument();
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Odjava" }));

    await waitFor(() => expect(router.push).toHaveBeenCalled());
    expect(router.push.mock.calls[0][0]).toBe("/sr-Latn");
    expect(paths).toEqual(["/auth/refresh", "/auth/me", "/auth/logout"]);
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
    expect(screen.getByRole("link", { name: "Prijava" })).toBeInTheDocument();
  });

  it("offers to sign in again when the session has ended elsewhere", async () => {
    keepAlice();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        json(401, { detail: "the refresh token is not valid" }),
      ),
    );

    renderIn("sr-Latn", <Account />);

    expect(
      await screen.findByRole("link", { name: "Prijava" }),
    ).toBeInTheDocument();
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });
});
