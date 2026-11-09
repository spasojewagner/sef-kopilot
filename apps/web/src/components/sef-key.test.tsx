import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ALICE, type Asked, json, keepSession, stubApi } from "@/test/api";
import { renderIn } from "@/test/render";

import { OrganizationSettings } from "./organization-settings";

const PRIMER = {
  id: "o-primer",
  name: "Primer d.o.o.",
  invoice_retention_days: null,
};
/** When an owner set Primer's key, and when the next one is set. */
const SET_AT = "2026-11-08T21:40:00Z";
const NOW = "2026-11-09T12:05:00Z";
/** A key as SEF generates one: never a real one. */
const KEY = "4711-4711-4711-4711";

/**
 * An API on which Alice holds ``role`` in Primer, which has a key since ``setAt``, or none. A
 * change of the key is answered by ``change`` when it is given; otherwise the key changes.
 */
function api({
  role = "owner",
  setAt = null,
  change,
}: {
  role?: string;
  setAt?: string | null;
  change?: (asked: Asked) => Response;
} = {}): Asked[] {
  let since = setAt;
  return stubApi((asked) => {
    if (asked.path === "/auth/me") {
      return json(200, { ...ALICE, role });
    }
    if (asked.path === "/api-keys") {
      return json(200, []);
    }
    if (asked.path === "/organization/sef-key") {
      if (change !== undefined) {
        return change(asked);
      }
      if (asked.method === "DELETE") {
        since = null;
        return new Response(null, { status: 204 });
      }
      since = NOW;
      return json(200, { set_at: NOW });
    }
    return json(200, { ...PRIMER, sef_key_set_at: since });
  });
}

const sent = (asked: Asked[]) =>
  asked
    .filter((request) => request.path === "/organization/sef-key")
    .map((request) =>
      request.method === "PUT"
        ? JSON.parse(String(request.body))
        : request.method,
    );

const user = () => userEvent.setup();

async function press(name: string) {
  await user().click(screen.getByRole("button", { name }));
}

describe("The organization's key to SEF", () => {
  it("shows every member since when a key is set, and only an owner changes it", async () => {
    keepSession();
    api({ role: "accountant", setAt: SET_AT });

    renderIn("sr-Latn", <OrganizationSettings />);

    expect(
      await screen.findByText("Ključ je postavljen 8. 11. 2026. 22:40."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Ključ za SEF postavlja vlasnik organizacije."),
    ).toBeInTheDocument();
    expect(
      screen.queryByLabelText("API ključ sa SEF-a"),
    ).not.toBeInTheDocument();
  });

  it("has an owner save a key once, which the field then forgets", async () => {
    keepSession();
    const asked = api();
    renderIn("sr-Latn", <OrganizationSettings />);
    expect(
      await screen.findByText(
        "Ključ nije postavljen: fakture organizacije se ne mogu slati na SEF.",
      ),
    ).toBeInTheDocument();

    const field = screen.getByLabelText("API ključ sa SEF-a");
    expect(field).toHaveAttribute("type", "password");
    expect(field).toHaveAttribute("autocomplete", "off");
    await user().type(field, `  ${KEY} `);
    await press("Sačuvaj ključ");

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Ključ je sačuvan.",
    );
    // Sent once, without the spaces around it, and no longer held by the page.
    expect(sent(asked)).toEqual([{ api_key: KEY }]);
    expect(screen.getByLabelText("Novi API ključ sa SEF-a")).toHaveValue("");
    expect(screen.queryByDisplayValue(KEY)).not.toBeInTheDocument();
    expect(
      screen.getByText("Ključ je postavljen 9. 11. 2026. 13:05."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zameni ključ" })).toBeDisabled();
  });

  it.each([["kratak"], ["4711 4711 4711"], ["ključ-4711-4711"]])(
    "sends nothing that cannot be a key: %j",
    async (written) => {
      keepSession();
      const asked = api();
      renderIn("en", <OrganizationSettings />);

      const field = await screen.findByLabelText("API key from SEF");
      await user().type(field, written);

      expect(field).toHaveAttribute("aria-invalid", "true");
      expect(field).toHaveAccessibleDescription(
        expect.stringContaining(
          "An API key from SEF is 8 to 200 visible characters, without spaces.",
        ),
      );
      expect(
        screen.getByRole("button", { name: "Save the key" }),
      ).toBeDisabled();
      expect(sent(asked)).toEqual([]);
    },
  );

  it("removes the key only once asked again", async () => {
    keepSession();
    const asked = api({ setAt: SET_AT });
    renderIn("sr-Latn", <OrganizationSettings />);
    await screen.findByText("Ključ je postavljen 8. 11. 2026. 22:40.");

    await press("Ukloni ključ");
    expect(
      screen.getByText(
        "Bez ključa SEF Kopilot ne može da šalje fakture vaše organizacije na SEF niti da pita gde su. Ključ na SEF-u ostaje kakav je: opozovite ga u podešavanjima SEF-a. Ukloniti ključ?",
      ),
    ).toBeInTheDocument();
    // The keyboard's focus follows the question, and comes back when it is cancelled.
    expect(
      screen.getByRole("button", { name: "Da, ukloni ključ" }),
    ).toHaveFocus();
    await press("Odustani");
    expect(screen.getByRole("button", { name: "Ukloni ključ" })).toHaveFocus();
    expect(sent(asked)).toEqual([]);

    await press("Ukloni ključ");
    await press("Da, ukloni ključ");

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Ključ je uklonjen.",
    );
    expect(sent(asked)).toEqual(["DELETE"]);
    expect(
      screen.getByText(
        "Ključ nije postavljen: fakture organizacije se ne mogu slati na SEF.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Ukloni ključ" }),
    ).not.toBeInTheDocument();
  });

  it.each([
    [
      503,
      "Ovaj server ne može da čuva ključeve za SEF: administrator treba da postavi SEF_FERNET_KEY.",
    ],
    [422, "API ključ sa SEF-a ima od 8 do 200 vidljivih znakova, bez razmaka."],
    [403, "Ključ nije promenjen: više niste vlasnik organizacije."],
    [429, "Previše zahteva. Pokušajte ponovo za 60 s."],
  ])("says why a key answered %s was not saved", async (status, message) => {
    keepSession();
    const asked = api({ change: () => json(status, { detail: "no" }) });
    renderIn("sr-Latn", <OrganizationSettings />);

    await user().type(await screen.findByLabelText("API ključ sa SEF-a"), KEY);
    await press("Sačuvaj ključ");

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    // Not saved, the key stays in the field, for the owner to try again.
    expect(screen.getByLabelText("API ključ sa SEF-a")).toHaveValue(KEY);
    if (status === 403) {
      await waitFor(() =>
        expect(
          asked.filter((request) => request.path === "/auth/me").length,
        ).toBeGreaterThan(1),
      );
    }
  });
});
