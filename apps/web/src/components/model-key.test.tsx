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
  sef_key_set_at: null,
};
/** When an owner set Primer's key, and when the next one is set. */
const SET_AT = "2026-11-08T21:40:00Z";
const NOW = "2026-11-09T12:05:00Z";
/** A key as a provider issues one: never a real one. */
const KEY = "own-model-key-4711";
const ANTHROPIC = { provider: "anthropic", model: "claude-x", set_at: SET_AT };

/**
 * An API on which Alice holds ``role`` in Primer, whose own key to a model is ``own``, or none.
 * A change of the key is answered by ``change`` when it is given; otherwise the key changes.
 */
function api({
  role = "owner",
  own = null,
  change,
}: {
  role?: string;
  own?: object | null;
  change?: (asked: Asked) => Response;
} = {}): Asked[] {
  let state = own;
  return stubApi((asked) => {
    if (asked.path === "/auth/me") {
      return json(200, { ...ALICE, role });
    }
    if (asked.path === "/api-keys") {
      return json(200, []);
    }
    if (asked.path === "/organization/model-key") {
      if (change !== undefined) {
        return change(asked);
      }
      if (asked.method === "DELETE") {
        state = null;
        return new Response(null, { status: 204 });
      }
      const { provider, model } = JSON.parse(String(asked.body));
      state = { provider, model, set_at: NOW };
      return json(200, state);
    }
    return json(200, { ...PRIMER, model_key: state });
  });
}

const sent = (asked: Asked[]) =>
  asked
    .filter((request) => request.path === "/organization/model-key")
    .map((request) =>
      request.method === "PUT"
        ? JSON.parse(String(request.body))
        : request.method,
    );

const user = () => userEvent.setup();

async function press(name: string) {
  await user().click(screen.getByRole("button", { name }));
}

describe("The organization's own language model", () => {
  it("shows every member whose model writes, and only an owner changes it", async () => {
    keepSession();
    api({ role: "accountant", own: ANTHROPIC });

    renderIn("sr-Latn", <OrganizationSettings />);

    expect(
      await screen.findByText(
        "Objašnjenja i ispravke organizacije piše Anthropic, model claude-x, sa ključem organizacije postavljenim 8. 11. 2026. 22:40.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Model bira vlasnik organizacije."),
    ).toBeInTheDocument();
    expect(
      screen.queryByLabelText("API ključ dobavljača"),
    ).not.toBeInTheDocument();
  });

  it("has an owner choose a provider and save a key once, which the field then forgets", async () => {
    keepSession();
    const asked = api();
    renderIn("sr-Latn", <OrganizationSettings />);
    expect(
      await screen.findByText(
        "Objašnjenja i ispravke organizacije piše model servera.",
      ),
    ).toBeInTheDocument();

    await user().selectOptions(screen.getByLabelText("Dobavljač"), "openai");
    // The provider's default model is shown until the owner names another.
    expect(screen.getByLabelText("Model (nije obavezno)")).toHaveAttribute(
      "placeholder",
      "gpt-6-luna",
    );
    const field = screen.getByLabelText("API ključ dobavljača");
    expect(field).toHaveAttribute("type", "password");
    expect(field).toHaveAttribute("autocomplete", "off");
    await user().type(field, `  ${KEY} `);
    await press("Sačuvaj ključ za model");

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Ključ je sačuvan: od sada piše model vašeg dobavljača.",
    );
    // Sent once, without the spaces around it, and no longer held by the page.
    expect(sent(asked)).toEqual([
      { provider: "openai", model: null, api_key: KEY },
    ]);
    expect(screen.getByLabelText("Novi API ključ dobavljača")).toHaveValue("");
    expect(screen.queryByDisplayValue(KEY)).not.toBeInTheDocument();
    expect(
      screen.getByText(
        "Objašnjenja i ispravke organizacije piše OpenAI, model podrazumevani, sa ključem organizacije postavljenim 9. 11. 2026. 13:05.",
      ),
    ).toBeInTheDocument();
  });

  it("sends the model an owner names, without the spaces around it", async () => {
    keepSession();
    const asked = api({ own: ANTHROPIC });
    renderIn("en", <OrganizationSettings />);

    // The provider the organization has is the one chosen to begin with.
    expect(await screen.findByLabelText("Provider")).toHaveValue("anthropic");
    await user().type(screen.getByLabelText("Model (optional)"), " claude-y ");
    await user().type(
      screen.getByLabelText("New API key from the provider"),
      KEY,
    );
    await press("Replace the model key");

    await screen.findByText(
      "The key is saved: your provider's model writes from now on.",
    );
    expect(sent(asked)).toEqual([
      { provider: "anthropic", model: "claude-y", api_key: KEY },
    ]);
  });

  it.each([["short"], ["a key with spaces"], ["ključ-4711-4711"]])(
    "sends nothing that cannot be a key: %j",
    async (written) => {
      keepSession();
      const asked = api();
      renderIn("en", <OrganizationSettings />);

      const field = await screen.findByLabelText("API key from the provider");
      await user().type(field, written);

      expect(field).toHaveAttribute("aria-invalid", "true");
      expect(field).toHaveAccessibleDescription(
        expect.stringContaining(
          "An API key is 8 to 300 visible characters, without spaces.",
        ),
      );
      expect(
        screen.getByRole("button", { name: "Save the model key" }),
      ).toBeDisabled();
      expect(sent(asked)).toEqual([]);
    },
  );

  it("sends nothing with a model that cannot be named so", async () => {
    keepSession();
    const asked = api();
    renderIn("en", <OrganizationSettings />);

    const model = await screen.findByLabelText("Model (optional)");
    await user().type(model, "gpt 6");
    await user().type(screen.getByLabelText("API key from the provider"), KEY);

    expect(model).toHaveAttribute("aria-invalid", "true");
    expect(model).toHaveAccessibleDescription(
      expect.stringContaining("A model's name begins with a letter or a digit"),
    );
    expect(
      screen.getByRole("button", { name: "Save the model key" }),
    ).toBeDisabled();
    expect(sent(asked)).toEqual([]);
  });

  it("removes the key only once asked again", async () => {
    keepSession();
    const asked = api({ own: ANTHROPIC });
    renderIn("sr-Latn", <OrganizationSettings />);
    await screen.findByText(/piše Anthropic, model claude-x/);

    await press("Ukloni ključ za model");
    expect(
      screen.getByText(
        "Bez ključa objašnjenja i ispravke vaše organizacije piše model servera, ili niko ako ga server nema. Ključ ostaje važeći kod dobavljača: opozovite ga tamo. Ukloniti ključ?",
      ),
    ).toBeInTheDocument();
    // The keyboard's focus follows the question, and comes back when it is cancelled.
    expect(
      screen.getByRole("button", { name: "Da, ukloni ključ za model" }),
    ).toHaveFocus();
    await press("Odustani");
    expect(
      screen.getByRole("button", { name: "Ukloni ključ za model" }),
    ).toHaveFocus();
    expect(sent(asked)).toEqual([]);

    await press("Ukloni ključ za model");
    await press("Da, ukloni ključ za model");

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Ključ je uklonjen: od sada piše model servera.",
    );
    expect(sent(asked)).toEqual(["DELETE"]);
    expect(
      screen.getByText(
        "Objašnjenja i ispravke organizacije piše model servera.",
      ),
    ).toBeInTheDocument();
  });

  it.each([
    [
      503,
      "Ovaj server ne može da čuva ključeve za model: administrator treba da postavi SEF_FERNET_KEY.",
    ],
    [
      422,
      "API je odbio ono što je poslato: proverite dobavljača, model i ključ.",
    ],
    [403, "Ključ nije promenjen: više niste vlasnik organizacije."],
    [429, "Previše zahteva. Pokušajte ponovo za 60 s."],
  ])("says why a key answered %s was not saved", async (status, message) => {
    keepSession();
    const asked = api({ change: () => json(status, { detail: "no" }) });
    renderIn("sr-Latn", <OrganizationSettings />);

    await user().type(
      await screen.findByLabelText("API ključ dobavljača"),
      KEY,
    );
    await press("Sačuvaj ključ za model");

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    // Not saved, the key stays in the field, for the owner to try again.
    expect(screen.getByLabelText("API ključ dobavljača")).toHaveValue(KEY);
    if (status === 403) {
      await waitFor(() =>
        expect(
          asked.filter((request) => request.path === "/auth/me").length,
        ).toBeGreaterThan(1),
      );
    }
  });
});
