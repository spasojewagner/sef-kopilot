import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { json, keepSession, stubApi } from "@/test/api";
import { invoice } from "@/test/invoices";
import { renderIn } from "@/test/render";

import { InvoiceList } from "./invoice-list";

describe("Invoice list", () => {
  it("shows each invoice with what the validator read and its verdict", async () => {
    keepSession();
    stubApi(() =>
      json(200, {
        invoices: [
          invoice(),
          invoice({ id: "c0ffee00-0000-4000-8000-000000000001", valid: true }),
        ],
        next: null,
      }),
    );

    renderIn("sr-Latn", <InvoiceList />);

    const rows = await screen.findAllByRole("row");
    expect(rows).toHaveLength(3);
    const first = within(rows[1]);
    expect(first.getByRole("link", { name: "F-2026-0042" })).toHaveAttribute(
      "href",
      "/sr-Latn/invoices/0b3f6a2e-1c4d-4e5f-8a9b-0c1d2e3f4a5b",
    );
    expect(first.getByText("Primer d.o.o. → Kupac a.d.")).toBeInTheDocument();
    expect(first.getByText("5. 11. 2026.")).toBeInTheDocument();
    expect(first.getByText("120.000,00 RSD")).toBeInTheDocument();
    expect(first.getByText("Neispravna")).toBeInTheDocument();
    expect(within(rows[2]).getByText("Ispravna")).toBeInTheDocument();
  });

  it("says so of a document the validator could not read", async () => {
    keepSession();
    stubApi(() =>
      json(200, { invoices: [invoice({ summary: null })], next: null }),
    );

    renderIn("sr-Latn", <InvoiceList />);

    expect(
      await screen.findByRole("link", { name: "Nečitljiv dokument" }),
    ).toBeInTheDocument();
  });

  it("shows the next page when asked, from where the last one ended", async () => {
    keepSession();
    const asked = stubApi(({ search }) =>
      search.includes("after=")
        ? json(200, {
            invoices: [invoice({ id: "c0ffee00-0000-4000-8000-000000000002" })],
            next: null,
          })
        : json(200, { invoices: [invoice()], next: "cursor-1" }),
    );
    renderIn("sr-Latn", <InvoiceList />);

    await userEvent
      .setup()
      .click(await screen.findByRole("button", { name: "Prikaži još" }));

    expect(await screen.findAllByRole("row")).toHaveLength(3);
    expect(asked.map((request) => request.search)).toEqual([
      "?limit=20",
      "?limit=20&after=cursor-1",
    ]);
    expect(
      screen.queryByRole("button", { name: "Prikaži još" }),
    ).not.toBeInTheDocument();
  });

  it("says when there is none yet", async () => {
    keepSession();
    stubApi(() => json(200, { invoices: [], next: null }));

    renderIn("en", <InvoiceList />);

    expect(
      await screen.findByText("No invoices yet. Send the first one above."),
    ).toBeInTheDocument();
  });

  it("says when the list could not be loaded", async () => {
    keepSession();
    stubApi(() => json(500, { detail: "Internal Server Error" }));

    renderIn("sr-Latn", <InvoiceList />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Fakture nisu učitane.",
    );
  });
});
