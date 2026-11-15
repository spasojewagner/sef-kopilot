import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { invoiceQuery, invoiceListKey } from "@/lib/queries";
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
  client.setQueryData(invoiceListKey, {
    pages: [{ invoices: [], next: null }],
    pageParams: [null],
  });
  renderIn(
    "sr-Latn",
    <InvoiceReading
      url="blob:racun"
      name={options.type === "application/pdf" ? "racun.pdf" : "racun.jpg"}
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

/** The panel that folds a part of the form away. */
function panelOf(name: string): HTMLElement {
  const panel = screen.getByRole("group", { name }).closest("details");
  if (panel === null) {
    throw new Error(`No panel holds ${name}`);
  }
  return panel;
}

/** The line a panel shows when it is folded: its title, what it holds, and its state. */
function summaryOf(name: string): HTMLElement {
  const summary = panelOf(name).querySelector("summary");
  if (summary === null) {
    throw new Error(`The panel of ${name} has no summary`);
  }
  return summary;
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
    // The panel stays open as the person left it, though nothing in it is missing now.
    expect(panelOf("Kupac")).toHaveAttribute("open");
  });

  it("sums the invoice up above its fields", async () => {
    reading();
    const user = userEvent.setup();
    const summary = within(
      screen.getByRole("region", { name: "Pregled fakture" }),
    );

    expect(summary.getByText("Račun (380)")).toBeInTheDocument();
    expect(summary.getByText("RF-2026-000123")).toBeInTheDocument();
    expect(summary.getByText("Izdata 5. 10. 2026.")).toBeInTheDocument();
    expect(summary.getByText("14.400,00 RSD")).toBeInTheDocument();
    expect(summary.getByText("bez PDV-a 12.000,00 RSD")).toBeInTheDocument();
    expect(summary.getByText("PDV 2.400,00 RSD")).toBeInTheDocument();
    expect(summary.getByText("Primer Softver d.o.o.")).toBeInTheDocument();
    expect(summary.getByText("PIB 100000024")).toBeInTheDocument();
    expect(summary.getByText("PIB nije pročitan")).toBeInTheDocument();

    await user.type(group("Kupac").getByLabelText("PIB"), "100000016");

    expect(summary.getByText("PIB 100000016")).toBeInTheDocument();
    expect(
      summary.getByText("Popunjeno je sve bez čega SEF ne prima fakturu."),
    ).toBeInTheDocument();
  });

  it("folds each part of the form under what it holds, opening those that need the person", () => {
    reading();

    expect(
      screen.getByText("Primer Softver d.o.o. · PIB 100000024 · Čačak"),
    ).toBeInTheDocument();
    expect(screen.getByText("1 stavka · 12.000,00 RSD")).toBeInTheDocument();
    expect(
      screen.getByText("160-0000000123456-78 · 97 12-345678-00123"),
    ).toBeInTheDocument();
    expect(panelOf("Prodavac")).not.toHaveAttribute("open");
    expect(panelOf("Stavke")).not.toHaveAttribute("open");
    expect(panelOf("Kupac")).toHaveAttribute("open");
    expect(
      within(summaryOf("Kupac")).getByRole("img", {
        name: "Treba vašu pažnju",
      }),
    ).toBeInTheDocument();
    expect(
      within(summaryOf("Prodavac")).getByRole("img", {
        name: "Ništa ne nedostaje",
      }),
    ).toBeInTheDocument();
  });

  it("opens a part on what the invoice cannot be made without", async () => {
    keepSession();
    const asked = drafting();
    reading({ fields: { ...READ, totals: { ...READ.totals, tax: null } } });
    const user = userEvent.setup();

    expect(panelOf("Ukupno")).not.toHaveAttribute("open");

    await user.click(
      screen.getByRole("button", { name: "Napravi fakturu i proveri" }),
    );

    expect(panelOf("Ukupno")).toHaveAttribute("open");
    expect(group("Ukupno").getByLabelText("Ukupan PDV")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(asked).toEqual([]);
  });

  it("sums a line up on one line, which opens on its fields", async () => {
    reading();
    const user = userEvent.setup();
    const amount = group("Stavke").getByLabelText("Iznos bez PDV-a");
    const line = amount.closest("details");

    expect(line).not.toBeNull();
    expect(line).not.toHaveAttribute("open");
    const row = within(screen.getAllByRole("listitem")[0]);
    expect(row.getByText("Konsultantski sat")).toBeInTheDocument();
    expect(row.getByText("8 HUR × 1.500,00 · S 20 %")).toBeInTheDocument();
    expect(row.getByText("12.000,00")).toBeInTheDocument();

    await user.click(row.getByText("Konsultantski sat"));

    expect(line).toHaveAttribute("open");
  });

  it("opens a line as it is added", async () => {
    reading();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Dodaj stavku" }));

    expect(
      group("Stavke")
        .getAllByLabelText("Iznos bez PDV-a")[1]
        .closest("details"),
    ).toHaveAttribute("open");
  });

  it("names every field SEF needs when nothing was read", () => {
    reading({ fields: {} });

    expect(screen.getByRole("status")).toHaveTextContent(
      "Popunite: Vrsta dokumenta, Broj, Datum izdavanja, Valuta, Naziv (Prodavac), PIB (Prodavac), Naziv (Kupac), PIB (Kupac), Stavke, Za plaćanje.",
    );
    expect(
      screen.getByText("Model nije pročitao nijednu stavku."),
    ).toBeInTheDocument();
  });

  it("is neither made nor downloaded without its type and what the UBL schema requires", async () => {
    keepSession();
    const asked = drafting();
    const [line] = READ.lines ?? [];
    reading({
      fields: {
        ...READ,
        type_code: null,
        lines: [{ ...line, net_amount: null }],
      },
    });
    const user = userEvent.setup();
    const type = group("Faktura").getByLabelText("Vrsta dokumenta");
    const amount = group("Stavke").getByLabelText("Iznos bez PDV-a");

    expect(type).toHaveAttribute("aria-invalid", "true");
    expect(amount).not.toHaveAttribute("aria-invalid");

    await user.click(screen.getByRole("button", { name: "Preuzmi XML" }));
    await user.click(
      screen.getByRole("button", { name: "Napravi fakturu i proveri" }),
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Popunite: Vrsta dokumenta, Iznos bez PDV-a (Stavka 1).",
    );
    expect(amount).toHaveAttribute("aria-invalid", "true");
    expect(asked).toEqual([]);

    await user.selectOptions(type, "386");
    await user.type(amount, "12000.00");

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(type).not.toHaveAttribute("aria-invalid");

    await user.click(
      screen.getByRole("button", { name: "Napravi fakturu i proveri" }),
    );

    await waitFor(() => expect(asked).toHaveLength(2));
    const sent = JSON.parse(String(asked[0].body));
    expect(sent.type_code).toBe("386");
    expect(sent.lines[0].net_amount).toBe("12000.00");
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
    const added = within(screen.getAllByRole("listitem")[1]);
    await user.type(added.getByLabelText("Naziv"), "Putni troškovi");
    await user.type(added.getByLabelText("Iznos bez PDV-a"), "800.00");
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
      net_amount: "800.00",
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

    await user.click(screen.getByRole("button", { name: "Dodaj stavku" }));
    await user.type(
      group("Stavke").getAllByLabelText("Iznos bez PDV-a")[1],
      "500.00",
    );
    await user.click(screen.getByRole("button", { name: "Ukloni stavku 1" }));
    await user.click(screen.getByRole("button", { name: "Ukloni red 1" }));
    await user.click(
      screen.getByRole("button", { name: "Napravi fakturu i proveri" }),
    );

    await waitFor(() => expect(asked).toHaveLength(2));
    const sent = JSON.parse(String(asked[0].body));
    expect(sent.lines).toEqual([
      expect.objectContaining({ name: null, net_amount: "500.00" }),
    ]);
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

  it("downloads the XML drafted of the fields once it is valid, keeping nothing", async () => {
    keepSession();
    const valid = { ...storedInvoice().report, valid: true, violations: [] };
    const asked = stubApi(({ path }) =>
      path === "/invoices/draft" ? new Response(DRAFT) : json(200, valid),
    );
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
    expect(asked.map(({ path }) => path)).toEqual([
      "/invoices/draft",
      "/invoices/validate",
    ]);
    expect(asked[1].search).toBe("?profile=srb");
    expect(asked[1].body).toBe(DRAFT);
    expect(given).toHaveBeenCalledWith("blob:draft");
    clicked.mockRestore();
  });

  it("keeps an XML that fails the check, says why, and forgets it once a field changes", async () => {
    keepSession();
    const { report } = storedInvoice();
    const fatal = report.violations.filter(
      ({ severity }) => severity === "fatal",
    );
    stubApi(({ path }) =>
      path === "/invoices/draft" ? new Response(DRAFT) : json(200, report),
    );
    const clicked = vi.spyOn(HTMLAnchorElement.prototype, "click");
    reading();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Preuzmi XML" }));

    const refused = await screen.findByRole("alert");
    expect(refused).toHaveTextContent(
      "XML nije prošao proveru, pa nije preuzet.",
    );
    for (const violation of report.violations) {
      if (fatal.includes(violation)) {
        expect(refused).toHaveTextContent(violation.message);
      } else {
        expect(refused).not.toHaveTextContent(violation.message);
      }
    }
    expect(clicked).not.toHaveBeenCalled();

    await user.type(group("Faktura").getByLabelText("Broj"), "-1");

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    clicked.mockRestore();
  });

  it.each([
    ["image/jpeg", "racun.jpg"],
    ["application/pdf", "racun.pdf"],
  ] as const)(
    "offers the %s chosen for download, under its name",
    (type, name) => {
      reading({ type });

      const original = screen.getByRole("link", { name: "Preuzmi original" });
      expect(original).toHaveAttribute("href", "blob:racun");
      expect(original).toHaveAttribute("download", name);
    },
  );

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
