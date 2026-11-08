import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { type Asked, json, keepSession, stubApi } from "@/test/api";
import { renderIn } from "@/test/render";

import { ApiKeys, dayAfter } from "./api-keys";

const PANTHEON = {
  id: "k-pantheon",
  name: "Pantheon",
  prefix: "sefk_AbCdEfG",
  // As the API lists them: in the order of their names.
  permissions: ["invoices:submit", "invoices:validate"],
  acts_for: "u-alice",
  created_at: "2026-11-01T09:00:00Z",
  expires_at: null,
  last_used_at: "2026-11-08T13:05:00Z",
};
const UNUSED = {
  ...PANTHEON,
  id: "k-unused",
  name: "Stari ERP",
  prefix: "sefk_ZyXwVuT",
  last_used_at: null,
  expires_at: "2026-12-31T23:00:00Z",
};

/**
 * An API that keeps ``keys``: a new one is issued as asked unless ``issue`` answers instead,
 * and a revoked one is gone.
 */
function api({
  keys = [PANTHEON],
  issue,
}: {
  keys?: object[];
  issue?: (asked: Asked) => Response;
} = {}): Asked[] {
  let kept = [...keys];
  return stubApi((asked) => {
    if (asked.method === "POST" && asked.path === "/api-keys") {
      if (issue !== undefined) {
        return issue(asked);
      }
      const body = JSON.parse(String(asked.body));
      const issued = { ...PANTHEON, id: "k-new", last_used_at: null, ...body };
      kept = [issued, ...kept];
      return json(201, { ...issued, key: "sefk_" + "s".repeat(43) });
    }
    if (asked.method === "DELETE") {
      kept = kept.filter(
        (key) => !asked.path.endsWith((key as { id: string }).id),
      );
      return new Response(null, { status: 204 });
    }
    return json(200, kept);
  });
}

const user = () => userEvent.setup();
const posted = (asked: Asked[]) =>
  asked
    .filter((request) => request.method === "POST")
    .map((request) => JSON.parse(String(request.body)));

describe("The API keys of the organization's page", () => {
  it("lists each key with what it allows and when it was last used", async () => {
    keepSession();
    api({ keys: [PANTHEON, UNUSED] });

    renderIn("sr-Latn", <ApiKeys role="client" />);

    const list = await screen.findByRole("list", { name: "Vaši ključevi" });
    const [pantheon, unused] = within(list).getAllByRole("listitem");
    expect(pantheon).toHaveTextContent("Pantheon");
    expect(pantheon).toHaveTextContent("sefk_AbCdEfG…");
    expect(pantheon).toHaveTextContent(
      "proveru faktura, čuvanje faktura i čitanje sačuvanih",
    );
    expect(pantheon).toHaveTextContent("8. 11. 2026.");
    expect(unused).toHaveTextContent("Još nije korišćen");
    expect(unused).toHaveTextContent("Prestaje da radi");
  });

  it("says so when there is no key", async () => {
    keepSession();
    api({ keys: [] });

    renderIn("en", <ApiKeys role="client" />);

    expect(
      await screen.findByText("You have no key that works."),
    ).toBeVisible();
  });

  it("issues a key with what was chosen and shows it once", async () => {
    keepSession();
    const asked = api({ keys: [] });
    renderIn("sr-Latn", <ApiKeys role="client" />);

    await user().type(
      await screen.findByLabelText("Za šta je ključ"),
      "  Minimax ",
    );
    await user().click(
      screen.getByLabelText("čuvanje faktura i čitanje sačuvanih"),
    );
    await user().click(screen.getByRole("button", { name: "Izdaj ključ" }));

    const shown = await screen.findByRole("region", {
      name: "Ključ „Minimax” je izdat",
    });
    expect(shown).toHaveFocus();
    expect(shown).toHaveTextContent("sefk_" + "s".repeat(43));
    expect(posted(asked)).toEqual([
      { name: "Minimax", permissions: ["invoices:validate"], expires_at: null },
    ]);
    expect(
      await screen.findByRole("list", { name: "Vaši ključevi" }),
    ).toHaveTextContent("Minimax");

    await user().click(screen.getByRole("button", { name: "Sačuvao sam ga" }));

    expect(
      screen.queryByText("sefk_" + "s".repeat(43)),
    ).not.toBeInTheDocument();
  });

  it("offers a client the permissions their role grants, and an accountant every invoice", async () => {
    keepSession();
    api();

    const { unmount } = renderIn("en", <ApiKeys role="client" />);
    expect(await screen.findByLabelText("checking invoices")).toBeChecked();
    expect(
      screen.queryByLabelText("every invoice of the organization"),
    ).not.toBeInTheDocument();
    unmount();

    renderIn("en", <ApiKeys role="accountant" />);
    expect(
      await screen.findByLabelText("every invoice of the organization"),
    ).not.toBeChecked();
  });

  it("issues a key that works through the day chosen", async () => {
    keepSession();
    const asked = api({ keys: [] });
    renderIn("en", <ApiKeys role="owner" />);

    await user().type(
      await screen.findByLabelText("What the key is for"),
      "Pantheon",
    );
    await user().type(
      screen.getByLabelText("Works until (optional)"),
      "2026-12-31",
    );
    await user().click(screen.getByRole("button", { name: "Issue the key" }));

    await screen.findByRole("region", { name: "The key “Pantheon” is issued" });
    expect(posted(asked)[0].expires_at).toBe(
      dayAfter("2026-12-31").toISOString(),
    );
    expect(dayAfter("2026-12-31").getDate()).toBe(1);
  });

  it("will not issue a key that allows nothing or has no name", async () => {
    keepSession();
    api();
    renderIn("en", <ApiKeys role="client" />);

    const issue = await screen.findByRole("button", { name: "Issue the key" });
    expect(issue).toBeDisabled();
    await user().type(screen.getByLabelText("What the key is for"), "Pantheon");
    expect(issue).toBeEnabled();
    await user().click(screen.getByLabelText("checking invoices"));
    await user().click(
      screen.getByLabelText("storing invoices and reading the stored ones"),
    );
    expect(issue).toBeDisabled();
  });

  it.each([
    [
      409,
      "Imate najviše ključeva koji rade. Opozovite neki koji vam ne treba.",
    ],
    [403, "Vaša uloga ne daje neku od izabranih dozvola."],
    [422, "Proverite naziv i datum: datum mora biti u budućnosti."],
  ])("says why a key was not issued (%i)", async (status, message) => {
    keepSession();
    api({ issue: () => json(status, { detail: "refused" }) });
    renderIn("sr-Latn", <ApiKeys role="client" />);

    await user().type(
      await screen.findByLabelText("Za šta je ključ"),
      "Pantheon",
    );
    await user().click(screen.getByRole("button", { name: "Izdaj ključ" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
  });

  it("revokes a key only once asked again, and lists the keys that still work", async () => {
    keepSession();
    const asked = api({ keys: [PANTHEON, UNUSED] });
    renderIn("sr-Latn", <ApiKeys role="client" />);

    const list = await screen.findByRole("list", { name: "Vaši ključevi" });
    const [pantheon] = within(list).getAllByRole("listitem");
    await user().click(
      within(pantheon).getByRole("button", { name: "Opozovi" }),
    );
    expect(pantheon).toHaveTextContent(
      "Ključ „Pantheon” prestaje da radi odmah, i mašina koja ga koristi gubi pristup.",
    );
    await user().click(
      within(pantheon).getByRole("button", { name: "Odustani" }),
    );
    expect(asked.filter((request) => request.method === "DELETE")).toEqual([]);

    await user().click(
      within(pantheon).getByRole("button", { name: "Opozovi" }),
    );
    await user().click(
      within(pantheon).getByRole("button", { name: "Da, opozovi ključ" }),
    );

    await waitFor(() => {
      expect(screen.queryByText("Pantheon")).not.toBeInTheDocument();
    });
    expect(
      asked
        .filter((request) => request.method === "DELETE")
        .map((request) => request.path),
    ).toEqual(["/api-keys/k-pantheon"]);
    expect(screen.getByText("Stari ERP")).toBeInTheDocument();
  });
});
