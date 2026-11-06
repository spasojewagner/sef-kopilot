import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderIn } from "@/test/render";

import { RegisterForm } from "./register-form";

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
  usePathname: () => "/sr-Latn/register",
}));

const TOKENS = {
  token_type: "bearer",
  access_token: "access-1",
  expires_in: 900,
  refresh_token: "refresh-1",
  refresh_expires_in: 2_592_000,
  user: { id: "u-alice", email: "alice@primer.example" },
  organization: { id: "o-primer", name: "Primer d.o.o." },
  role: "owner",
};

function stubRegister(response: () => Response) {
  const bodies: Record<string, unknown>[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_input: RequestInfo | URL, init: RequestInit = {}) => {
      bodies.push(JSON.parse(String(init.body)));
      return response();
    }),
  );
  return bodies;
}

async function registerAs(
  email: string,
  password: string,
  organization: string,
) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Adresa e-pošte"), email);
  await user.type(screen.getByLabelText("Lozinka"), password);
  await user.type(screen.getByLabelText("Naziv organizacije"), organization);
  await user.click(screen.getByRole("button", { name: "Napravi nalog" }));
}

describe("Registration form", () => {
  it("creates the account with its organization, and goes home", async () => {
    router.replace.mockClear();
    const bodies = stubRegister(
      () =>
        new Response(JSON.stringify(TOKENS), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        }),
    );
    renderIn("sr-Latn", <RegisterForm />);

    await registerAs(
      "alice@primer.example",
      "a long passphrase",
      "Primer d.o.o.",
    );

    await waitFor(() => expect(router.replace).toHaveBeenCalled());
    expect(router.replace.mock.calls[0][0]).toBe("/sr-Latn");
    expect(bodies).toEqual([
      {
        email: "alice@primer.example",
        password: "a long passphrase",
        organization_name: "Primer d.o.o.",
      },
    ]);
  });

  it("says that the address has an account already", async () => {
    stubRegister(
      () =>
        new Response(
          JSON.stringify({
            detail: "an account with this e-mail address exists already",
          }),
          { status: 409, headers: { "Content-Type": "application/json" } },
        ),
    );
    renderIn("sr-Latn", <RegisterForm />);

    await registerAs(
      "alice@primer.example",
      "a long passphrase",
      "Primer d.o.o.",
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Za ovu adresu već postoji nalog.",
    );
  });

  it("asks for a password of 12 to 128 characters, and says so", () => {
    renderIn("sr-Latn", <RegisterForm />);

    const password = screen.getByLabelText("Lozinka");
    expect(password).toHaveAttribute("minlength", "12");
    expect(password).toHaveAttribute("maxlength", "128");
    expect(password).toHaveAccessibleDescription("Od 12 do 128 znakova.");
    expect(password).toHaveAttribute("autocomplete", "new-password");
  });
});
