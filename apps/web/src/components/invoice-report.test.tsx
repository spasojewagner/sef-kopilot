import { screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { invoiceQuery } from "@/lib/queries";
import { aMoment, json, keepSession, stubApi } from "@/test/api";
import { storedInvoice, stubReportApi } from "@/test/invoices";
import { renderIn, testQueryClient } from "@/test/render";

import { InvoiceReport } from "./invoice-report";

// The report offers the model's repair, which opens the repair's page when it is written.
vi.mock("next/navigation", async (importOriginal) => ({
  ...(await importOriginal<typeof import("next/navigation")>()),
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
  }),
}));

const ID = "0b3f6a2e-1c4d-4e5f-8a9b-0c1d2e3f4a5b";

describe("Invoice report", () => {
  it("shows what the validator read from the invoice, and its verdict", async () => {
    keepSession();
    const asked = stubReportApi();

    renderIn("sr-Latn", <InvoiceReport id={ID} />);

    expect(
      await screen.findByRole("heading", { level: 1, name: "F-2026-0042" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Neispravna")).toBeInTheDocument();
    expect(screen.getByText("Kupac a.d.")).toBeInTheDocument();
    expect(screen.getByText("5. 11. 2026.")).toBeInTheDocument();
    expect(screen.getByText("120.000,00 RSD")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "1 greška, 1 upozorenje" }),
    ).toBeInTheDocument();
    expect(asked.map((request) => request.path)).toEqual([
      `/invoices/${ID}`,
      `/invoices/${ID}/repairs`,
    ]);
  });

  it("offers the model's repair only of an invalid invoice that patches apply to", async () => {
    keepSession();
    const invalid = storedInvoice();
    const valid = {
      ...invalid,
      report: { ...invalid.report, valid: true, violations: [] },
    };
    const notXml = {
      ...invalid,
      report: {
        ...invalid.report,
        layers: invalid.report.layers.map((layer) =>
          layer.layer === "xml" ? { ...layer, violations: 1 } : layer,
        ),
      },
    };

    for (const [stored, offered] of [
      [invalid, true],
      [valid, false],
      [notXml, false],
    ] as const) {
      stubReportApi({ stored });
      const { unmount } = renderIn("sr-Latn", <InvoiceReport id={ID} />);
      const repairs = await screen.findByRole("heading", {
        level: 2,
        name: "Popravke",
      });
      const section = within(repairs.closest("section") as HTMLElement);
      expect(
        section.queryByRole("button", { name: "Predloži popravku" }) !== null,
      ).toBe(offered);
      unmount();
    }
  });

  it("lists each rule with every place it fails, the errors first", async () => {
    keepSession();
    stubReportApi();

    renderIn("sr-Latn", <InvoiceReport id={ID} />);

    const rules = await screen.findAllByRole("heading", { level: 3 });
    expect(rules.map((rule) => rule.textContent)).toEqual([
      "SRB-009",
      "BR-CO-15",
    ]);
    const first = within(rules[0].closest("[data-slot=card]") as HTMLElement);
    expect(first.getByText("Greška")).toBeInTheDocument();
    expect(first.getByText("SRB-CIUS")).toBeInTheDocument();
    expect(
      first.getByText(
        "The seller's PIB must have nine digits with a valid check digit.",
      ),
    ).toHaveAttribute("lang", "en");
    expect(first.getByText("1 mesto")).toBeInTheDocument();
    expect(first.getByText("red 31")).toBeInTheDocument();
    expect(
      first.getByText(
        "/ubl:Invoice/cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID",
      ),
    ).toBeInTheDocument();
  });

  it("shows what each layer of the validator found", async () => {
    keepSession();
    stubReportApi();

    renderIn("en", <InvoiceReport id={ID} />);

    const layers = await screen.findByRole("region", {
      name: "Layers of the check",
    });
    expect(within(layers).getAllByRole("listitem")).toHaveLength(5);
    expect(within(layers).getByText("EN 16931 UBL 1.3.16")).toHaveAttribute(
      "lang",
      "en",
    );
    expect(within(layers).getAllByText("1 violation")).toHaveLength(2);
  });

  it("says when the invoice does not exist, or is not the visitor's", async () => {
    keepSession();
    stubApi(() => json(404, { detail: "no such invoice" }));

    renderIn("sr-Latn", <InvoiceReport id={ID} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Ova faktura ne postoji, ili nije vaša.",
    );
    expect(
      screen.getByRole("link", { name: "Nazad na fakture" }),
    ).toHaveAttribute("href", "/sr-Latn/invoices");
  });

  it("says so too of an address whose id is not an invoice's", async () => {
    keepSession();
    stubApi(() =>
      json(422, { detail: [{ msg: "Input should be a valid UUID" }] }),
    );

    renderIn("sr-Latn", <InvoiceReport id="not-an-id" />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Ova faktura ne postoji, ili nije vaša.",
    );
  });

  it("says what the validator could not place, left out or did not run", async () => {
    keepSession();
    const stored = storedInvoice();
    stubReportApi({
      stored: {
        ...stored,
        report: {
          ...stored.report,
          violations: [
            {
              rule_id: "XSD",
              severity: "fatal",
              message: "The document is not a UBL 2.1 invoice.",
              xpath: null,
              layer: "xsd",
              code: null,
              line: null,
            },
          ],
          set_aside: [
            {
              violation: stored.report.violations[1],
              reason: "recomputed under its own id",
              replaced_by: ["BR-CO-15"],
            },
          ],
          layers: [
            { layer: "xml", ran: true, violations: 0, note: null },
            { layer: "xsd", ran: true, violations: 1, note: null },
            { layer: "schematron", ran: false, violations: 0, note: null },
            { layer: "srb-cius", ran: false, violations: 0, note: null },
            { layer: "arithmetic", ran: false, violations: 0, note: null },
          ],
          omitted: 3,
        },
      },
    });

    renderIn("sr-Latn", <InvoiceReport id={ID} />);

    const heading = await screen.findByRole("heading", {
      level: 3,
      name: "XSD",
    });
    const rule = within(heading.closest("[data-slot=card]") as HTMLElement);
    // The whole document, and no line, since the validator could not name one.
    expect(rule.getByRole("listitem")).toHaveTextContent(/^ceo dokument$/);
    expect(
      screen.getByText("Prekršaja koje izveštaj ne prikazuje: 3."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Nalaza objavljenih pravila koje ovaj profil ne primenjuje: 1.",
      ),
    ).toBeInTheDocument();
    expect(screen.getAllByText("nije pokrenut")).toHaveLength(3);
  });

  it("shows a document's values as text, whatever they hold", async () => {
    keepSession();
    const markup = '<img src="x" onerror="alert(1)">';
    const stored = storedInvoice({
      summary: {
        document_type: "Invoice",
        number: "F-2026-0042",
        issue_date: "2026-11-05",
        currency: "RSD",
        seller: markup,
        buyer: "Kupac a.d.",
        payable_amount: "120000.00",
      },
    });
    stored.report.violations[0].message = `The seller is not '${markup}'.`;
    stubReportApi({ stored });

    const { container } = renderIn("sr-Latn", <InvoiceReport id={ID} />);

    expect(await screen.findByText(markup)).toBeInTheDocument();
    expect(
      screen.getByText(`The seller is not '${markup}'.`),
    ).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });

  it("shows the report the upload brought without asking for it again", async () => {
    keepSession();
    const asked = stubReportApi();
    const client = testQueryClient();
    client.setQueryData(invoiceQuery(ID).queryKey, storedInvoice());

    renderIn("sr-Latn", <InvoiceReport id={ID} />, client);
    await aMoment();

    expect(
      screen.getByRole("heading", { level: 1, name: "F-2026-0042" }),
    ).toBeInTheDocument();
    expect(asked.map((request) => request.path)).toEqual([
      `/invoices/${ID}/repairs`,
    ]);
  });
});
