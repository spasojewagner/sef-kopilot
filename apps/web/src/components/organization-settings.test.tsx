import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ALICE, type Asked, json, keepSession, stubApi } from "@/test/api";
import { renderIn } from "@/test/render";

import { OrganizationSettings } from "./organization-settings";

const PRIMER = { id: "o-primer", name: "Primer d.o.o." };

/**
 * An API on which Alice holds ``role`` in Primer, which keeps its invoices ``days``. A change of
 * the period is answered by ``change`` when it is given; otherwise the period changes, and the
 * answer is the organization.
 */
function api({
  role = "owner",
  days = null,
  change,
}: {
  role?: string;
  days?: number | null;
  change?: (asked: Asked) => Response | Promise<Response>;
} = {}): Asked[] {
  let kept = days;
  return stubApi((asked) => {
    if (asked.path === "/auth/me") {
      return json(200, { ...ALICE, role });
    }
    if (asked.path === "/api-keys") {
      return json(200, []);
    }
    if (asked.method === "PATCH" && change !== undefined) {
      return change(asked);
    }
    if (asked.method === "PATCH") {
      kept = JSON.parse(String(asked.body)).invoice_retention_days;
    }
    return json(200, { ...PRIMER, invoice_retention_days: kept });
  });
}

const changes = (asked: Asked[]) =>
  asked
    .filter((request) => request.method === "PATCH")
    .map((request) => JSON.parse(String(request.body)));
const reads = (asked: Asked[]) =>
  asked.filter((r) => r.method === "GET" && r.path === "/organization").length;

async function choose(value: string) {
  await userEvent
    .setup()
    .selectOptions(await screen.findByLabelText("Čuvaj fakture"), value);
}

async function press(name: string) {
  await userEvent.setup().click(screen.getByRole("button", { name }));
}

describe("The organization's page", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows every member the organization, who they are in it, and how long it keeps invoices", async () => {
    keepSession();
    api({ role: "client" });

    renderIn("sr-Latn", <OrganizationSettings />);

    expect(await screen.findByText("klijent")).toBeInTheDocument();
    expect(screen.getByText("Primer d.o.o.")).toBeInTheDocument();
    expect(screen.getByText("alice@primer.example")).toBeInTheDocument();
    expect(
      screen.getByText("Fakture se čuvaju dok ih neko ne obriše."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Rok čuvanja menja vlasnik organizacije."),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Čuvaj fakture")).not.toBeInTheDocument();
  });

  it.each([
    [
      "sr-Latn" as const,
      730,
      "Svaka faktura se čuva 2 godine od dana kada je sačuvana, a zatim se briše sa izveštajem i popravkama.",
    ],
    [
      "sr-Latn" as const,
      21,
      "Svaka faktura se čuva 21 dan od dana kada je sačuvana, a zatim se briše sa izveštajem i popravkama.",
    ],
    [
      "en" as const,
      365,
      "Each invoice is kept for 1 year after the day it was stored, then deleted with its report and repairs.",
    ],
  ])(
    "writes a period in %s, in years when it is whole ones (%i)",
    async (locale, days, said) => {
      keepSession();
      api({ role: "accountant", days });

      renderIn(locale, <OrganizationSettings />);

      expect(await screen.findByText(said)).toBeInTheDocument();
    },
  );

  it("offers an owner the periods, and the one the organization has among them", async () => {
    keepSession();
    api({ days: 45 });

    renderIn("sr-Latn", <OrganizationSettings />);

    const periods = await screen.findByLabelText("Čuvaj fakture");
    expect(periods).toHaveValue("45");
    expect(
      [...(periods as HTMLSelectElement).options].map((option) => option.text),
    ).toEqual([
      "30 dana",
      "45 dana",
      "90 dana",
      "180 dana",
      "1 godinu",
      "2 godine",
      "5 godina",
      "10 godina",
      "Dok ih neko ne obriše",
    ]);
    expect(screen.getByRole("button", { name: "Sačuvaj" })).toBeDisabled();
  });

  it("keeps invoices longer at once: nothing is deleted", async () => {
    keepSession();
    const asked = api({ days: 30 });
    renderIn("sr-Latn", <OrganizationSettings />);

    await choose("365");
    await press("Sačuvaj");

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Rok čuvanja je sačuvan.",
    );
    expect(changes(asked)).toEqual([{ invoice_retention_days: 365 }]);
    expect(
      screen.getByText(
        "Svaka faktura se čuva 1 godinu od dana kada je sačuvana, a zatim se briše sa izveštajem i popravkama.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sačuvaj" })).toBeDisabled();
  });

  it("sets a period only after a second press that says which invoices it deletes", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-07T12:00:00Z"));
    keepSession();
    const asked = api();
    renderIn("sr-Latn", <OrganizationSettings />);

    await choose("90");
    await press("Sačuvaj");

    expect(
      screen.getByText(
        "Fakture sačuvane zaključno sa 9. 8. 2026. biće obrisane pri sledećem brisanju, najkasnije za jedan dan, sa izveštajima i popravkama, i to se ne može poništiti. Menjate rok čuvanja?",
      ),
    ).toBeInTheDocument();
    // The keyboard's focus follows the question, and comes back when it is cancelled.
    expect(
      screen.getByRole("button", { name: "Da, promeni rok" }),
    ).toHaveFocus();
    await press("Odustani");
    expect(screen.getByRole("button", { name: "Sačuvaj" })).toHaveFocus();
    expect(changes(asked)).toEqual([]);
    await press("Sačuvaj");
    await press("Da, promeni rok");

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Rok čuvanja je sačuvan.",
    );
    expect(changes(asked)).toEqual([{ invoice_retention_days: 90 }]);
    expect(
      screen.getByText(
        "Svaka faktura se čuva 90 dana od dana kada je sačuvana, a zatim se briše sa izveštajem i popravkama.",
      ),
    ).toBeInTheDocument();
  });

  it("asks before a shorter period too, and not before keeping every invoice", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-07T12:00:00Z"));
    keepSession();
    const asked = api({ days: 365 });
    renderIn("en", <OrganizationSettings />);

    await userEvent
      .setup()
      .selectOptions(await screen.findByLabelText("Keep invoices"), "30");
    await press("Save");
    expect(
      screen.getByText(
        "Invoices stored on or before Oct 8, 2026 will be deleted at the next deletion, within a day, with their reports and repairs, and that cannot be undone. Change the period?",
      ),
    ).toBeInTheDocument();
    await press("Cancel");
    await userEvent
      .setup()
      .selectOptions(screen.getByLabelText("Keep invoices"), "keep");
    await press("Save");

    expect(await screen.findByRole("status")).toHaveTextContent(
      "The period is saved.",
    );
    expect(changes(asked)).toEqual([{ invoice_retention_days: null }]);
    expect(
      screen.getByText("Invoices are kept until someone deletes them."),
    ).toBeInTheDocument();
  });

  it("tells an owner demoted meanwhile that nothing changed, and follows the role", async () => {
    keepSession();
    let role = "owner";
    stubApi((asked) => {
      if (asked.path === "/auth/me") {
        return json(200, { ...ALICE, role });
      }
      if (asked.path === "/api-keys") {
        return json(200, []);
      }
      if (asked.method === "PATCH") {
        role = "accountant";
        return json(403, {
          detail: "requires the permission organization:manage",
        });
      }
      return json(200, { ...PRIMER, invoice_retention_days: 30 });
    });
    renderIn("sr-Latn", <OrganizationSettings />);

    await choose("365");
    await press("Sačuvaj");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Rok čuvanja nije promenjen: više niste vlasnik organizacije.",
    );
    expect(await screen.findByText("računovođa")).toBeInTheDocument();
    expect(
      screen.getByText("Rok čuvanja menja vlasnik organizacije."),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Čuvaj fakture")).not.toBeInTheDocument();
  });

  it.each([
    [
      () => Promise.reject(new TypeError("Failed to fetch")),
      "API ne odgovara. Rok čuvanja se ponovo učitava: proverite ga pre nego što pokušate ponovo.",
    ],
    [
      () => json(502, { detail: "bad gateway" }),
      "API nije jasno odgovorio. Rok čuvanja je ponovo učitan: proverite ga pre nego što pokušate ponovo.",
    ],
  ])(
    "reads the period again when the change's outcome is not known here (%#)",
    async (change, said) => {
      keepSession();
      const asked = api({ days: 30, change });
      renderIn("sr-Latn", <OrganizationSettings />);

      await choose("365");
      await press("Sačuvaj");

      expect(await screen.findByRole("alert")).toHaveTextContent(said);
      await waitFor(() => expect(reads(asked)).toBe(2));
    },
  );

  it.each([
    [
      () => json(429, { detail: "too many" }, { "Retry-After": "12" }),
      "Previše zahteva. Pokušajte ponovo za 12 s.",
    ],
    [
      () => json(422, { detail: [] }),
      "Rok čuvanja nije promenjen. Pokušajte ponovo malo kasnije.",
    ],
  ])(
    "says why a change was refused, and reads nothing again (%#)",
    async (change, said) => {
      keepSession();
      const asked = api({ days: 30, change });
      renderIn("sr-Latn", <OrganizationSettings />);

      await choose("365");
      await press("Sačuvaj");

      expect(await screen.findByRole("alert")).toHaveTextContent(said);
      expect(reads(asked)).toBe(1);
    },
  );

  it("says so when the organization cannot be read", async () => {
    keepSession();
    stubApi((asked) =>
      asked.path === "/auth/me"
        ? json(200, ALICE)
        : json(500, { detail: "Internal Server Error" }),
    );

    renderIn("sr-Latn", <OrganizationSettings />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Organizacija nije učitana. Pokušajte ponovo malo kasnije.",
    );
  });
});
