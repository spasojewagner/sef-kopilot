import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { STORAGE_KEY } from "@/lib/session";
import { renderIn } from "@/test/render";

import { SignInForm } from "./sign-in-form";

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
  usePathname: () => "/sr-Latn/sign-in",
}));

const ALICE = {
  user: { id: "u-alice", email: "alice@primer.example" },
  organization: { id: "o-primer", name: "Primer d.o.o." },
  role: "owner",
};

const TOKENS = {
  token_type: "bearer",
  access_token: "access-1",
  expires_in: 900,
  refresh_token: "refresh-1",
  refresh_expires_in: 2_592_000,
  ...ALICE,
};

function json(status: number, body: unknown, headers: HeadersInit = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

/** The API answers each sign-in with ``answer``; the bodies it was sent are returned. */
function stubSignIn(answer: (body: Record<string, unknown>) => Response) {
  const bodies: Record<string, unknown>[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_input: RequestInfo | URL, init: RequestInit = {}) => {
      const body = JSON.parse(String(init.body));
      bodies.push(body);
      return answer(body);
    }),
  );
  return bodies;
}

async function signInAs(email: string, password: string) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Adresa e-pošte"), email);
  await user.type(screen.getByLabelText("Lozinka"), password);
  await user.click(screen.getByRole("button", { name: "Prijavi se" }));
  return user;
}

describe("Sign-in form", () => {
  it("signs in with the address and the password, and goes home", async () => {
    router.replace.mockClear();
    const bodies = stubSignIn(() => json(200, TOKENS));
    renderIn("sr-Latn", <SignInForm />);

    await signInAs("alice@primer.example", "a long passphrase");

    await waitFor(() => expect(router.replace).toHaveBeenCalled());
    expect(router.replace.mock.calls[0][0]).toBe("/sr-Latn");
    expect(bodies).toEqual([
      {
        email: "alice@primer.example",
        password: "a long passphrase",
        organization_id: null,
      },
    ]);
    expect(localStorage.getItem(STORAGE_KEY)).toContain("refresh-1");
  });

  it("stays on the page that holds it, when that page says what follows", async () => {
    router.replace.mockClear();
    stubSignIn(() => json(200, TOKENS));
    const onSignedIn = vi.fn();
    renderIn("sr-Latn", <SignInForm onSignedIn={onSignedIn} />);

    await signInAs("alice@primer.example", "a long passphrase");

    await waitFor(() => expect(onSignedIn).toHaveBeenCalledOnce());
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("says that the address or the password is wrong", async () => {
    stubSignIn(() =>
      json(401, { detail: "invalid e-mail address or password" }),
    );
    renderIn("sr-Latn", <SignInForm />);

    await signInAs("alice@primer.example", "not the passphrase");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Adresa ili lozinka nije tačna.",
    );
  });

  it("lets a member of several organizations choose the one to sign in to", async () => {
    router.replace.mockClear();
    const bodies = stubSignIn((body) =>
      body.organization_id === "o-2"
        ? json(200, TOKENS)
        : json(409, {
            detail: "choose an organization: send its id as organization_id",
            organizations: [
              {
                organization: { id: "o-1", name: "Prva d.o.o." },
                role: "owner",
              },
              {
                organization: { id: "o-2", name: "Druga d.o.o." },
                role: "client",
              },
            ],
          }),
    );
    renderIn("sr-Latn", <SignInForm />);

    const user = await signInAs("alice@primer.example", "a long passphrase");
    const choice = await screen.findByRole("group", {
      name: "Član ste više organizacija. U koju se prijavljujete?",
    });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await user.click(
      within(choice).getByRole("button", { name: "Druga d.o.o." }),
    );

    await waitFor(() => expect(router.replace).toHaveBeenCalled());
    expect(bodies.map((body) => body.organization_id)).toEqual([null, "o-2"]);
  });

  it("says how long to wait after too many attempts", async () => {
    stubSignIn(() =>
      json(429, { detail: "too many requests" }, { "Retry-After": "30" }),
    );
    renderIn("sr-Latn", <SignInForm />);

    await signInAs("alice@primer.example", "a long passphrase");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Previše pokušaja. Pokušajte ponovo za 30 s.",
    );
  });

  it("says so when the API cannot be reached", async () => {
    // vitest.setup.ts answers no request: each fails as if the API could not be reached.
    renderIn("sr-Latn", <SignInForm />);

    await signInAs("alice@primer.example", "a long passphrase");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "API ne odgovara. Pokušajte ponovo malo kasnije.",
    );
  });

  it("says who is signed in, rather than asking again", () => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        refreshToken: "refresh-1",
        refreshExpiresAt: Date.now() + 3_600_000,
        identity: ALICE,
      }),
    );

    renderIn("en", <SignInForm />);

    expect(
      screen.getByText("You are signed in as alice@primer.example."),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Back to the home page" }),
    ).toHaveAttribute("href", "/en");
  });

  it("asks in English too, and leads to the registration", () => {
    renderIn("en", <SignInForm />);

    expect(
      screen.getByRole("heading", { level: 1, name: "Sign in" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Register" })).toHaveAttribute(
      "href",
      "/en/register",
    );
  });
});
