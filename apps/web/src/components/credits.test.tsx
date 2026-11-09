import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ALICE, type Asked, json, keepSession, stubApi } from "@/test/api";
import { renderIn } from "@/test/render";

import { CONFIRMING_EVERY_MS } from "./credits";
import { OrganizationSettings } from "./organization-settings";

const PRIMER = {
  id: "o-primer",
  name: "Primer d.o.o.",
  invoice_retention_days: null,
  sef_key_set_at: null,
  model_key: null,
};
const OFF = {
  enabled: false,
  balance: null,
  starting: null,
  per_invoice: null,
  packs: [],
};
const PACKS = [
  { credits: 100, price: 1000, currency: "eur" },
  { credits: 500, price: 4000, currency: "eur" },
];
const ON = {
  enabled: true,
  balance: 23,
  starting: 25,
  per_invoice: 1,
  packs: PACKS,
};
const ENTRIES = [
  {
    id: "e-2",
    at: "2026-11-09T12:05:00Z",
    kind: "spend",
    delta: -1,
    invoice_id: "i-1",
  },
  {
    id: "e-1",
    at: "2026-11-09T12:00:00Z",
    kind: "opening",
    delta: 25,
    invoice_id: null,
  },
];
const STRIPE_PAGE = "https://checkout.stripe.com/c/pay/cs_test_4711";

/**
 * An API on which Alice holds ``role`` in Primer, whose billing is ``billing``; a checkout is
 * answered by ``checkout`` when it is given.
 */
function api({
  role = "owner",
  billing = ON,
  checkout,
}: {
  role?: string;
  billing?: object;
  checkout?: (asked: Asked) => Response;
} = {}): Asked[] {
  return stubApi((asked) => {
    switch (asked.path) {
      case "/auth/me":
        return json(200, { ...ALICE, role });
      case "/api-keys":
        return json(200, []);
      case "/billing":
        return json(200, billing);
      case "/billing/entries":
        return json(200, ENTRIES);
      case "/billing/checkout":
        return checkout ? checkout(asked) : json(201, { url: STRIPE_PAGE });
      default:
        return json(200, PRIMER);
    }
  });
}

const user = () => userEvent.setup();

afterEach(() => {
  window.history.replaceState(null, "", "/");
});

describe("The organization's credits", () => {
  it("are not shown where storing costs nothing", async () => {
    keepSession();
    const asked = api({ billing: OFF });

    renderIn("en", <OrganizationSettings />);

    await screen.findByText("Primer d.o.o.");
    await waitFor(() =>
      expect(asked.some((request) => request.path === "/billing")).toBe(true),
    );
    expect(
      screen.queryByRole("heading", { name: "Credits" }),
    ).not.toBeInTheDocument();
  });

  it("show every member how many are left, and only the owner what to buy", async () => {
    keepSession();
    const asked = api({ role: "client" });

    renderIn("sr-Latn", <OrganizationSettings />);

    expect(
      await screen.findByText(
        "Organizacija ima 23 kredita; sačuvana faktura košta 1.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Kredite dokupljuje vlasnik organizacije."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /kredita za/ })).toBeNull();
    expect(asked.some((request) => request.path === "/billing/entries")).toBe(
      false,
    );
  });

  it("show the owner the packs on sale and the latest changes", async () => {
    keepSession();
    api();

    renderIn("en", <OrganizationSettings />);

    expect(
      await screen.findByRole("button", { name: "100 credits for €10.00" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "500 credits for €40.00" }),
    ).toBeInTheDocument();
    const table = await screen.findByRole("table", {
      name: "The latest changes of the organization's credits",
    });
    expect(table).toHaveTextContent("An invoice stored");
    expect(table).toHaveTextContent("-1");
    expect(table).toHaveTextContent("Starting credits");
    expect(table).toHaveTextContent("+25");
  });

  it("send the owner to Stripe's page for the pack chosen", async () => {
    keepSession();
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign, search: "" });
    const asked = api();
    renderIn("en", <OrganizationSettings />);

    await user().click(
      await screen.findByRole("button", { name: "500 credits for €40.00" }),
    );

    await waitFor(() => expect(assign).toHaveBeenCalledWith(STRIPE_PAGE));
    const checkout = asked.find(
      (request) => request.path === "/billing/checkout",
    );
    expect(checkout?.method).toBe("POST");
    expect(JSON.parse(String(checkout?.body))).toEqual({ credits: 500 });
    vi.unstubAllGlobals();
  });

  it.each([
    [502, "Stripe did not open the page. Try again a little later."],
    [503, "This server sells no credits: its operator gives them."],
    [403, "You are no longer the organization's owner."],
  ])("say why a checkout answered %s did not open", async (status, message) => {
    keepSession();
    api({ checkout: () => json(status, { detail: "no" }) });
    renderIn("en", <OrganizationSettings />);

    await user().click(
      await screen.findByRole("button", { name: "100 credits for €10.00" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
  });

  it("say that a payment is on its way, and read the credits again", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    keepSession();
    window.history.replaceState(null, "", "/en/organization?checkout=paid");
    const asked = api();

    renderIn("en", <OrganizationSettings />);

    expect(
      await screen.findByText(/^Stripe took the payment\./),
    ).toHaveAttribute("role", "status");
    await vi.advanceTimersByTimeAsync(CONFIRMING_EVERY_MS * 2);
    await waitFor(() =>
      expect(
        asked.filter((request) => request.path === "/billing").length,
      ).toBeGreaterThan(1),
    );
    vi.useRealTimers();
  });

  it("say that a cancelled payment charged nothing", async () => {
    keepSession();
    window.history.replaceState(
      null,
      "",
      "/sr-Latn/organization?checkout=cancelled",
    );
    api();

    renderIn("sr-Latn", <OrganizationSettings />);

    expect(
      await screen.findByText("Plaćanje je otkazano: ništa nije naplaćeno."),
    ).toHaveAttribute("role", "status");
  });

  it("tell the owner where the server sells none", async () => {
    keepSession();
    api({ billing: { ...ON, packs: [] } });

    renderIn("en", <OrganizationSettings />);

    expect(
      await screen.findByText(
        "This server sells no credits: its operator gives them.",
      ),
    ).toBeInTheDocument();
  });
});
