import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { invoiceQuery, invoicesQuery } from "@/lib/queries";
import { json, keepSession, stubApi, type Asked } from "@/test/api";
import { extraction, READ } from "@/test/extraction";
import { storedInvoice } from "@/test/invoices";
import { renderIn, testQueryClient } from "@/test/render";

import { InvoiceReading } from "./invoice-reading";

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
  usePathname: () => "/sr-Latn/invoices",
}));

const DRAFT = "<?xml version='1.0' encoding='UTF-8'?>\n<Invoice/>";

function reading(
  options: {
    fields?: typeof READ;
    type?: "image/jpeg" | "application/pdf";
    onDiscard?: () => void;
  } = {},
) {
  const client = testQueryClient();
  client.setQueryData(invoicesQuery.queryKey, {
    pages: [{ invoices: [], next: null }],
    pageParams: [null],
  });
  renderIn(
    "sr-Latn",
    <InvoiceReading
      url="blob:racun"
      type={options.type ?? "image/jpeg"}
      extraction={extraction(options.fields ?? READ)}
      profile="srb"
      onDiscard={options.onDiscard ?? (() => {})}
    />,
    client,
  );
  return client;
}

/** The API: a draft of the fields, then the invoice stored. */
function drafting(stored = storedInvoice()) {
  return stubApi((asked: Asked) =>
    asked.path === "/invoices/draft"
      ? new Response(DRAFT, {
          status: 200,
          headers: { "Content-Type": "application/xml" },
        })
      : json(201, stored),
  );
}

function group(name: string) {
  return within(screen.getByRole("group", { name }));
}

afterEach(() => {
  router.push.mockClear();
});

describe("An invoice read from a picture", () => {
  it("is shown beside the picture, every field as it was read, marked beta", () => {
    reading();

    expect(
      screen.getByRole("heading", { name: "Pročitano sa slike" }),
    ).toBeInTheDocument();
    expect(screen.getByText("beta")).toBeInTheDocument();
    expect(
      screen.getByText("Pročitao: groq/qwen/qwen3.8-27b"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", {
        name: "Dokument iz koga su polja pročitana",
      }),
    ).toHaveAttribute("src", "blob:racun");
    // A tap opens it at its full size, where a phone's screen can read it.
    expect(
      screen.getByRole("link", { name: "Dokument iz koga su polja pročitana" }),
    ).toHaveAttribute("href", "blob:racun");
    expect(screen.getByRole("note")).toHaveTextContent(
      "Proverite svako polje prema dokumentu i ispravite ga.",
    );
    expect(group("Faktura").getByLabelText("Broj")).toHaveValue(
      "RF-2026-000123",
    );
    expect(group("Faktura").getByLabelText("Vrsta dokumenta")).toHaveValue(
      "380",
    );
    expect(group("Prodavac").getByLabelText("PIB")).toHaveValue("100000024");
    expect(group("Prodavac").getByLabelText("U sistemu PDV-a")).toHaveValue(
      "yes",
    );
    expect(group("Stavke").getByLabelText("Količina")).toHaveValue("8");
    expect(group("Stavke").getByLabelText("Kategorija PDV-a")).toHaveValue("S");
    expect(group("Ukupno").getByLabelText("Za plaćanje")).toHaveValue(
      "14400.00",
    );
    expect(group("Plaćanje").getByLabelText("Poziv na broj")).toHaveValue(
      "12-345678-00123",
    );
  });

  it("names and marks what SEF needs that was not read, until it is filled in", async () => {
    reading();
    const user = userEvent.setup();
    const buyersPib = group("Kupac").getByLabelText("PIB");

    expect(screen.getByRole("status")).toHaveTextContent(
      "Nedostaje ono bez čega SEF ne prima fakturuPopunite: PIB (Kupac).",
    );
    expect(buyersPib).toHaveAttribute("aria-invalid", "true");
    expect(group("Prodavac").getByLabelText("PIB")).not.toHaveAttribute(
      "aria-invalid",
    );

    await user.type(buyersPib, "100000016");

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(buyersPib).not.toHaveAttribute("aria-invalid");
  });

  it("names every field SEF needs when nothing was read", () => {
    reading({ fields: {} });

    expect(screen.getByRole("status")).toHaveTextContent(
      "Popunite: Broj, Datum izdavanja, Valuta, Naziv (Prodavac), PIB (Prodavac), Naziv (Kupac), PIB (Kupac), Stavke, Za plaćanje.",
    );
    expect(
      screen.getByText("Model nije pročitao nijednu stavku."),
    ).toBeInTheDocument();
  });

  it("is made, as corrected, into an invoice that is kept and checked", async () => {
    keepSession();
    const stored = storedInvoice();
    const asked = drafting(stored);
    const client = reading();
    const user = userEvent.setup();

    const number = group("Faktura").getByLabelText("Broj");
    await user.clear(number);
    await user.type(number, "RF-2026-000124");
    await user.type(group("Kupac").getByLabelText("PIB"), "100000016");
    await user.click(screen.getByRole("button", { name: "Dodaj stavku" }));
    await user.type(
      within(screen.getAllByRole("listitem")[1]).getByLabelText("Naziv"),
      "Putni troškovi",
    );
    await user.click(
      screen.getByRole("button", { name: "Napravi fakturu i proveri" }),
    );

    await waitFor(() => expect(router.push).toHaveBeenCalled());
    expect(router.push.mock.calls[0][0]).toBe(`/sr-Latn/invoices/${stored.id}`);
    expect(asked.map(({ method, path }) => `${method} ${path}`)).toEqual([
      "POST /invoices/draft",
      "POST /invoices",
    ]);
    const sent = JSON.parse(String(asked[0].body));
    expect(sent.number).toBe("RF-2026-000124");
    expect(sent.buyer.tax_id).toBe("100000016");
    expect(sent.lines).toHaveLength(2);
    expect(sent.lines[1]).toEqual({
      name: "Putni troškovi",
      quantity: null,
      unit: null,
      unit_price: null,
      net_amount: null,
      vat_category: null,
      vat_rate: null,
    });
    expect(asked[1].search).toBe("?profile=srb");
    expect(asked[1].headers.get("Content-Type")).toBe("application/xml");
    expect(await (asked[1].body as Blob).text()).toBe(DRAFT);
    expect(client.getQueryData(invoiceQuery(stored.id).queryKey)).toEqual(
      stored,
    );
  });

  it("lets a line and a row of the recapitulation go", async () => {
    keepSession();
    const asked = drafting();
    reading();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Ukloni stavku 1" }));
    await user.click(screen.getByRole("button", { name: "Ukloni red 1" }));
    await user.click(
      screen.getByRole("button", { name: "Napravi fakturu i proveri" }),
    );

    await waitFor(() => expect(asked).toHaveLength(2));
    const sent = JSON.parse(String(asked[0].body));
    expect(sent.lines).toEqual([]);
    expect(sent.vat_breakdown).toEqual([]);
  });

  it("says which form a field must have when the API refuses the fields", async () => {
    keepSession();
    const asked = stubApi(() =>
      json(422, {
        detail: [{ loc: ["body", "issue_date"], msg: "write a date" }],
      }),
    );
    reading();
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Napravi fakturu i proveri" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Neko polje nije u obliku koji se traži: datum kao 2026-10-05, iznos kao 14400.00, kodovi velikim slovima.",
    );
    expect(asked).toHaveLength(1);
    expect(router.push).not.toHaveBeenCalled();
  });

  it("says why the invoice made was not kept", async () => {
    keepSession();
    stubApi((asked) =>
      asked.path === "/invoices/draft"
        ? new Response(DRAFT, { status: 200 })
        : json(402, { detail: "no credit" }),
    );
    reading();
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Napravi fakturu i proveri" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Organizacija nema više kredita za čuvanje fakture.",
    );
  });

  it("downloads the XML drafted of the fields, keeping nothing", async () => {
    keepSession();
    const asked = drafting();
    const made = vi.fn(() => "blob:draft");
    const given = vi.fn();
    vi.stubGlobal(
      "URL",
      Object.assign(URL, { createObjectURL: made, revokeObjectURL: given }),
    );
    const clicked = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(function (this: HTMLAnchorElement) {
        expect(this.download).toBe("RF-2026-000123.xml");
        expect(this.href).toBe("blob:draft");
      });
    reading();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Preuzmi XML" }));

    await waitFor(() => expect(clicked).toHaveBeenCalledOnce());
    expect(asked.map(({ path }) => path)).toEqual(["/invoices/draft"]);
    expect(given).toHaveBeenCalledWith("blob:draft");
    clicked.mockRestore();
  });

  it("is discarded on request", async () => {
    const discard = vi.fn();
    reading({ onDiscard: discard });

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Odustani" }));

    expect(discard).toHaveBeenCalledOnce();
  });
});

describe("An invoice read from a PDF", () => {
  it("is shown beside the PDF in the browser's viewer, with a link to open it", () => {
    reading({ type: "application/pdf" });

    expect(
      screen.getByRole("heading", { name: "Pročitano iz PDF-a" }),
    ).toBeInTheDocument();
    const shown = screen.getByLabelText("Dokument iz koga su polja pročitana");
    expect(shown.tagName).toBe("OBJECT");
    expect(shown).toHaveAttribute("data", "blob:racun");
    const links = screen.getAllByRole("link", {
      name: "Otvorite PDF u novoj kartici",
    });
    expect(links).toHaveLength(2);
    links.forEach((link) => expect(link).toHaveAttribute("href", "blob:racun"));
    // What a browser without a viewer of its own shows instead.
    expect(within(shown).getByText(/ne prikazuje PDF/)).toBeInTheDocument();
    expect(within(shown).getByRole("link")).toHaveAttribute("target", "_blank");
  });
});
