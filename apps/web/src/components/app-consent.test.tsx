import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ALICE, type Asked, json, keepSession, stubApi } from "@/test/api";
import { renderIn } from "@/test/render";

import { AppConsent } from "./app-consent";

vi.mock("next/navigation", async (importOriginal) => ({
  ...(await importOriginal<typeof import("next/navigation")>()),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/sr-Latn/oauth/consent",
}));

const CALLBACK = "http://127.0.0.1:6274/oauth/callback";

/** What the MCP Inspector asks, as the API shows it to the person deciding. */
const REQUEST = {
  id: "r-1",
  client_id: "c-1",
  client_name: "Inspektor",
  redirect_uri: CALLBACK,
  scopes: ["invoices:validate"],
  withheld: [],
  expires_at: "2026-11-07T21:32:00Z",
};

const APPROVED = `${CALLBACK}?code=c0de&state=xyz&iss=https%3A%2F%2Fapi.example`;
const REFUSED = `${CALLBACK}?error=access_denied&state=xyz&iss=https%3A%2F%2Fapi.example`;

/**
 * An API on which Alice signs in and out, and the request waits for her: it is read as
 * ``request``, or answered by ``read`` when given; an approval or a refusal is answered by
 * ``decided`` when given, or else with the client's address and its answer.
 */
function api({
  request = REQUEST,
  read,
  decided,
}: {
  request?: object;
  read?: () => Response;
  decided?: (asked: Asked) => Response;
} = {}): Asked[] {
  return stubApi((asked) => {
    if (asked.path === "/auth/me") {
      return json(200, ALICE);
    }
    if (asked.path === "/auth/login") {
      return json(200, {
        token_type: "bearer",
        access_token: "access-1",
        expires_in: 900,
        refresh_token: "refresh-1",
        refresh_expires_in: 2_592_000,
        ...ALICE,
      });
    }
    if (asked.path === "/auth/logout") {
      return new Response(null, { status: 204 });
    }
    if (asked.method === "POST" && decided !== undefined) {
      return decided(asked);
    }
    if (asked.path.endsWith("/approval")) {
      return json(200, { redirect_uri: APPROVED });
    }
    if (asked.path.endsWith("/refusal")) {
      return json(200, { redirect_uri: REFUSED });
    }
    return read?.() ?? json(200, request);
  });
}

const decisions = (asked: Asked[]) =>
  asked
    .filter(({ method }) => method === "POST")
    .map(({ path }) => path)
    .filter((path) => path.startsWith("/oauth/"));

async function press(name: string) {
  await userEvent.setup().click(screen.getByRole("button", { name }));
}

describe("The page where a person decides on a client's request", () => {
  it("shows what the client asks, where the person returns, and where it will work", async () => {
    keepSession();
    const asked = api();

    renderIn("sr-Latn", <AppConsent requestId="r-1" goTo={vi.fn()} />);

    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: "Aplikacija traži dozvolu",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Inspektor")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Ime koje je aplikacija sama sebi dala; SEF Kopilot ga nije proverio.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("127.0.0.1:6274")).toBeInTheDocument();
    expect(
      screen.getByText("Aplikacija na ovom računaru, ne sajt."),
    ).toBeInTheDocument();
    expect(screen.getByText("Primer d.o.o.")).toBeInTheDocument();
    expect(screen.getByText("Kao alice@primer.example")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Moći će da" })).toHaveTextContent(
      "proverava fakture i objašnjava njihove greške",
    );
    expect(
      screen.getByText("Zahtev čeka vašu odluku do 22:32."),
    ).toBeInTheDocument();
    const read = asked.find(({ path }) => path === "/oauth/requests/r-1");
    expect(read?.headers.get("Authorization")).toBe("Bearer access-2");
  });

  it("names a client without a name as such, a site by its host, and a scope it has no words for by itself", async () => {
    keepSession();
    api({
      request: {
        ...REQUEST,
        client_name: null,
        redirect_uri: "https://claude.ai/api/mcp/auth_callback",
        scopes: ["invoices:validate", "invoices:submit", "members:manage"],
      },
    });

    renderIn("en", <AppConsent requestId="r-1" goTo={vi.fn()} />);

    expect(await screen.findByText("No name")).toBeInTheDocument();
    expect(screen.getByText("claude.ai")).toBeInTheDocument();
    expect(
      screen.queryByText("An app on this computer, not a site."),
    ).not.toBeInTheDocument();
    const scopes = screen.getByRole("list", { name: "It will be able to" });
    expect(scopes).toHaveTextContent(
      "validate invoices and explain their errors",
    );
    expect(scopes).toHaveTextContent(
      "store invoices in your organization and read the ones you sent",
    );
    expect(scopes).toHaveTextContent("members:manage");
  });

  it("names apart what the person's role withholds, which approving does not give", async () => {
    keepSession();
    api({
      request: {
        ...REQUEST,
        scopes: ["invoices:validate", "invoices:send"],
        withheld: ["invoices:send"],
      },
    });

    renderIn("en", <AppConsent requestId="r-1" goTo={vi.fn()} />);

    const allowed = await screen.findByRole("list", {
      name: "It will be able to",
    });
    expect(allowed).toHaveTextContent(
      "validate invoices and explain their errors",
    );
    expect(allowed).not.toHaveTextContent("SEF");
    expect(
      screen.getByRole("list", {
        name: "Your role does not allow it, so it will not be able to",
      }),
    ).toHaveTextContent(
      "send the invoices you stored to SEF's demo environment, in your organization's name",
    );
    expect(screen.getByRole("button", { name: "Allow" })).toBeEnabled();
  });

  it("lets the person only deny a client whose every scope their role withholds", async () => {
    keepSession();
    const asked = api({
      request: {
        ...REQUEST,
        scopes: ["invoices:send"],
        withheld: ["invoices:send"],
      },
    });

    renderIn("sr-Latn", <AppConsent requestId="r-1" goTo={vi.fn()} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Vaša uloga u organizaciji ne dozvoljava ništa od onoga što aplikacija traži.",
    );
    expect(
      screen.queryByRole("list", { name: "Moći će da" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("list", {
        name: "Vaša uloga to ne dozvoljava, pa neće moći da",
      }),
    ).toHaveTextContent(
      "šalje fakture koje ste vi sačuvali na SEF demo, u ime vaše organizacije",
    );
    expect(screen.getByRole("button", { name: "Dozvoli" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Odbij" })).toBeEnabled();
    expect(decisions(asked)).toEqual([]);
  });

  it("names the host that published the description of a client known by its document", async () => {
    keepSession();
    api({
      request: {
        ...REQUEST,
        client_id: "https://assistant.example/oauth/client.json",
        client_name: "Claude",
      },
    });

    renderIn("sr-Latn", <AppConsent requestId="r-1" goTo={vi.fn()} />);

    expect(await screen.findByText("Claude")).toBeInTheDocument();
    expect(
      screen.getByText("Opis aplikacije objavljen je na"),
    ).toBeInTheDocument();
    // Whatever name it gives itself, the host it was read from is what vouches for it.
    expect(screen.getByText("assistant.example")).toBeInTheDocument();
    expect(
      screen.getByText(
        "SEF Kopilot je opis pročitao sa ove adrese: za aplikaciju stoji onaj ko njome upravlja.",
      ),
    ).toBeInTheDocument();
  });

  it("names no publisher for a client that registered itself", async () => {
    keepSession();
    api();

    renderIn("en", <AppConsent requestId="r-1" goTo={vi.fn()} />);

    expect(await screen.findByText("Inspektor")).toBeInTheDocument();
    expect(
      screen.queryByText("The app's description is published at"),
    ).not.toBeInTheDocument();
  });

  it("allows the client, and takes the person back to it with its code", async () => {
    keepSession();
    const asked = api();
    const goTo = vi.fn();
    renderIn("sr-Latn", <AppConsent requestId="r-1" goTo={goTo} />);
    await screen.findByText("Inspektor");

    await press("Dozvoli");

    await waitFor(() => expect(goTo).toHaveBeenCalledWith(APPROVED));
    expect(decisions(asked)).toEqual(["/oauth/requests/r-1/approval"]);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Vraćamo vas na 127.0.0.1:6274…",
    );
    for (const name of ["Dozvoli", "Odbij", "Prijavi se drugim nalogom"]) {
      expect(screen.getByRole("button", { name })).toBeDisabled();
    }
  });

  it("denies the client, and takes the person back to it with the refusal", async () => {
    keepSession();
    const asked = api();
    const goTo = vi.fn();
    renderIn("sr-Latn", <AppConsent requestId="r-1" goTo={goTo} />);
    await screen.findByText("Inspektor");

    await press("Odbij");

    await waitFor(() => expect(goTo).toHaveBeenCalledWith(REFUSED));
    expect(decisions(asked)).toEqual(["/oauth/requests/r-1/refusal"]);
  });

  it("says a request no longer waits, when it expired or was decided before it was read", async () => {
    keepSession();
    api({ read: () => json(404, { detail: "no such request" }) });

    renderIn("sr-Latn", <AppConsent requestId="r-1" goTo={vi.fn()} />);

    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: "Zahtev više ne čeka odluku",
      }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("says a request no longer waits, when it expired while the person read it", async () => {
    keepSession();
    const goTo = vi.fn();
    api({ decided: () => json(404, { detail: "no such request" }) });
    renderIn("sr-Latn", <AppConsent requestId="r-1" goTo={goTo} />);
    await screen.findByText("Inspektor");

    await press("Dozvoli");

    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: "Zahtev više ne čeka odluku",
      }),
    ).toBeInTheDocument();
    expect(goTo).not.toHaveBeenCalled();
  });

  it.each([
    [
      403,
      "Vaša uloga u organizaciji ne dozvoljava ništa od onoga što aplikacija traži.",
    ],
    [500, "Odluka nije poslata. Pokušajte ponovo."],
  ])(
    "says why an approval answered %s did not go through, and lets the person decide again",
    async (status, message) => {
      keepSession();
      const goTo = vi.fn();
      api({ decided: () => json(status, { detail: "no" }) });
      renderIn("sr-Latn", <AppConsent requestId="r-1" goTo={goTo} />);
      await screen.findByText("Inspektor");

      await press("Dozvoli");

      expect(await screen.findByRole("alert")).toHaveTextContent(message);
      expect(goTo).not.toHaveBeenCalled();
      expect(screen.getByRole("button", { name: "Odbij" })).toBeEnabled();
    },
  );

  it("has a visitor who is not signed in sign in here, then shows them the request", async () => {
    const asked = api();
    renderIn("sr-Latn", <AppConsent requestId="r-1" goTo={vi.fn()} />);

    expect(
      await screen.findByText(
        "Aplikacija traži da u vaše ime radi u SEF Kopilotu. Prijavite se da vidite šta traži i da odlučite.",
      ),
    ).toBeInTheDocument();
    expect(asked).toEqual([]);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Adresa e-pošte"), ALICE.user.email);
    await user.type(screen.getByLabelText("Lozinka"), "a long passphrase");
    await user.click(screen.getByRole("button", { name: "Prijavi se" }));

    expect(await screen.findByText("Inspektor")).toBeInTheDocument();
  });

  it("signs the person out, to sign in with another account", async () => {
    keepSession();
    const asked = api();
    renderIn("sr-Latn", <AppConsent requestId="r-1" goTo={vi.fn()} />);
    await screen.findByText("Inspektor");

    await press("Prijavi se drugim nalogom");

    expect(
      await screen.findByRole("heading", { level: 1, name: "Prijava" }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(asked.some(({ path }) => path === "/auth/logout")).toBe(true),
    );
    expect(decisions(asked)).toEqual([]);
  });

  it("says what to do when the address names no request", async () => {
    keepSession();
    const asked = api();

    renderIn("sr-Latn", <AppConsent requestId={null} goTo={vi.fn()} />);

    expect(
      screen.getByRole("heading", { level: 1, name: "Nema zahteva" }),
    ).toBeInTheDocument();
    expect(asked).toEqual([]);
  });
});
