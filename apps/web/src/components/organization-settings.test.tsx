import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ALICE, json, keepSession, stubApi } from "@/test/api";
import { renderIn } from "@/test/render";

import { OrganizationSettings } from "./organization-settings";

const PRIMER = { id: "o-primer", name: "Primer d.o.o." };

/** An API on which Alice holds ``role`` in Primer, which keeps its invoices ``days``. */
function api({
  role = "owner",
  days = null,
}: { role?: string; days?: number | null } = {}): void {
  stubApi((asked) =>
    asked.path === "/auth/me"
      ? json(200, { ...ALICE, role })
      : json(200, { ...PRIMER, invoice_retention_days: days }),
  );
}

describe("The organization's page", () => {
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
