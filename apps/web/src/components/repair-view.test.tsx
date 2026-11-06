import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { formatMoment } from "@/lib/format";
import { json, keepSession, stubApi } from "@/test/api";
import { storedInvoice } from "@/test/invoices";
import { repair } from "@/test/repairs";
import { renderIn } from "@/test/render";

import { RepairView } from "./repair-view";

const ID = storedInvoice().id;
const REPAIR = repair().id;

function section(name: string) {
  const heading = screen.getByRole("heading", { level: 2, name });
  return within(heading.closest("section") as HTMLElement);
}

/** The facts under the page's heading: what each is, and its value. */
async function facts() {
  const heading = await screen.findByRole("heading", { level: 1 });
  return within(heading.closest("header") as HTMLElement)
    .getAllByRole("term")
    .map((term) => [term.textContent, term.nextElementSibling?.textContent]);
}

describe("A repair's page", () => {
  it("says who proposed the repair, when, and where it stands", async () => {
    keepSession();
    const asked = stubApi(() =>
      json(200, repair({ model: "openai/gpt-oss-120b" })),
    );

    renderIn("sr-Latn", <RepairView invoiceId={ID} repairId={REPAIR} />);

    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: "Popravka od 6. 11. 2026. 11:30",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Čeka odluku")).toBeInTheDocument();
    expect(await facts()).toEqual([
      ["Predložio", "vi, uz jezički model openai/gpt-oss-120b"],
    ]);
    expect(asked.map((request) => request.path)).toEqual([
      `/invoices/${ID}/repairs/${REPAIR}`,
    ]);
  });

  it("says who decided on it, and when", async () => {
    keepSession();
    stubApi(() =>
      json(
        200,
        repair({
          status: "rejected",
          proposed_by: "u-bob",
          decided_by: "u-alice",
          decided_at: "2026-11-06T12:00:00Z",
        }),
      ),
    );

    renderIn("sr-Latn", <RepairView invoiceId={ID} repairId={REPAIR} />);

    expect(await facts()).toEqual([
      ["Predložio", "drugi član"],
      ["Odbio", "vi, 6. 11. 2026. 13:00"],
    ]);
  });

  it("says who approved it even when their account is gone", async () => {
    keepSession();
    stubApi(() =>
      json(
        200,
        repair({
          status: "approved",
          decided_by: null,
          decided_at: "2026-11-06T12:00:00Z",
        }),
      ),
    );

    renderIn("sr-Latn", <RepairView invoiceId={ID} repairId={REPAIR} />);

    expect(await facts()).toEqual([
      ["Predložio", "vi"],
      ["Odobrio", "bivši član, 6. 11. 2026. 13:00"],
    ]);
  });

  it("says when it was superseded, which no person decides", async () => {
    keepSession();
    const decided = "2026-11-06T12:00:00Z";
    stubApi(() =>
      json(200, repair({ status: "superseded", decided_at: decided })),
    );

    renderIn("en", <RepairView invoiceId={ID} repairId={REPAIR} />);

    expect(await facts()).toEqual([
      ["Proposed by", "you"],
      [
        "Superseded",
        `${formatMoment("en", decided)}, when another repair was approved`,
      ],
    ]);
  });

  it("shows what became of each patch, and why", async () => {
    keepSession();
    stubApi(() => json(200, repair()));

    renderIn("sr-Latn", <RepairView invoiceId={ID} repairId={REPAIR} />);

    await screen.findByRole("heading", { level: 2, name: "Izmene" });
    const patches = section("Izmene").getAllByRole("listitem");
    expect(patches.map((patch) => patch.textContent)).toEqual([
      "Primenjenazameni/ubl:Invoice/cbc:InvoiceTypeCode393 → 380Razlog: SRB-001 dopušta samo 380, 381, 383 i 386.",
      "Čeka odluku čovekazameni/ubl:Invoice/cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyIDPredložena vrednost: RS100000024Razlog: Kontrolna cifra PIB-a prodavca.it touches a tax identifier (cac:PartyTaxScheme): a person decides it",
      "Nije primenjenaukloni/ubl:Invoice/cbc:Note[2]Razlog: Druga napomena je suvišna.there is nothing at /ubl:Invoice/cbc:Note[2] to remove",
    ]);
    for (const problem of [
      "it touches a tax identifier (cac:PartyTaxScheme): a person decides it",
      "there is nothing at /ubl:Invoice/cbc:Note[2] to remove",
    ]) {
      expect(screen.getByText(problem)).toHaveAttribute("lang", "en");
    }
    expect(
      section("Izmene").getByText(/o njoj odlučuje čovek\.$/),
    ).toBeInTheDocument();
  });

  it("says what a patch that added or removed changed, and no guard's note when none waits", async () => {
    keepSession();
    stubApi(() =>
      json(
        200,
        repair({
          applied: 2,
          needs_decision: 0,
          failed: 0,
          outcomes: [
            {
              patch: {
                xpath: "/ubl:Invoice/cbc:BuyerReference",
                op: "add",
                value: "PO-2026-118",
                reason: "Peppol traži referencu kupca ili narudžbine.",
              },
              status: "applied",
              problem: null,
              before: null,
              after: "PO-2026-118",
            },
            {
              patch: {
                xpath: "/ubl:Invoice/cbc:Note",
                op: "remove",
                value: null,
                reason: "Napomena je suvišna.",
              },
              status: "applied",
              problem: null,
              before: "Rok za plaćanje je 15 dana od datuma prometa.",
              after: null,
            },
          ],
        }),
      ),
    );

    renderIn("sr-Latn", <RepairView invoiceId={ID} repairId={REPAIR} />);

    await screen.findByRole("heading", { level: 2, name: "Izmene" });
    const patches = section("Izmene");
    expect(patches.getByText("ništa → PO-2026-118")).toBeInTheDocument();
    expect(
      patches.getByText(
        "Rok za plaćanje je 15 dana od datuma prometa. → ništa",
      ),
    ).toBeInTheDocument();
    expect(
      patches.queryByText(/o njoj odlučuje čovek/),
    ).not.toBeInTheDocument();
  });

  it("shows the difference line by line, marking what is removed and added", async () => {
    keepSession();
    stubApi(() => json(200, repair()));

    renderIn("sr-Latn", <RepairView invoiceId={ID} repairId={REPAIR} />);

    // A line wider than the screen scrolls in its box, which the keyboard can reach.
    const box = await screen.findByRole("group", { name: "Razlika u fakturi" });
    expect(box).toHaveAttribute("tabindex", "0");
    const lines = within(box).getAllByRole("listitem");
    expect(lines.map((line) => line.textContent)).toEqual([
      "⋯Ovde su izostavljeni redovi koji se ne menjaju.",
      "    <cbc:IssueDate>2026-10-05</cbc:IssueDate>",
      "    <cbc:DueDate>2026-10-20</cbc:DueDate>",
      "- uklonjeno:   <cbc:InvoiceTypeCode>393</cbc:InvoiceTypeCode>",
      "+ dodato:   <cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>",
      "    <cbc:Note>Rok za plaćanje je 15 dana od datuma prometa.</cbc:Note>",
      "    <cbc:DocumentCurrencyCode>RSD</cbc:DocumentCurrencyCode>",
    ]);
    expect(within(lines[3]).getByRole("deletion")).toBeInTheDocument();
    expect(within(lines[4]).getByRole("insertion")).toBeInTheDocument();
  });

  it("says so when the patches change nothing", async () => {
    keepSession();
    stubApi(() => json(200, repair({ changed: false, diff: "" })));

    renderIn("en", <RepairView invoiceId={ID} repairId={REPAIR} />);

    expect(
      await screen.findByText("These changes do not change the invoice."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("group")).not.toBeInTheDocument();
  });

  it("shows the report on the invoice the repair would leave", async () => {
    keepSession();
    const left = storedInvoice().report;
    stubApi(() => json(200, repair({ valid: false, report: left })));

    renderIn("sr-Latn", <RepairView invoiceId={ID} repairId={REPAIR} />);

    await screen.findByRole("heading", {
      level: 2,
      name: "Izveštaj posle izmena",
    });
    const after = section("Izveštaj posle izmena");
    expect(after.getByText("Neispravna")).toBeInTheDocument();
    expect(
      after
        .getAllByRole("heading", { level: 3 })
        .map((rule) => rule.textContent),
    ).toEqual(["SRB-009", "BR-CO-15"]);
    expect(
      screen.getByRole("heading", { level: 2, name: "Slojevi provere" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Nazad na izveštaj" }),
    ).toHaveAttribute("href", `/sr-Latn/invoices/${ID}`);
  });

  it("says so when the repair is not there, its id is refused, or it did not load", async () => {
    keepSession();
    const answers = [
      json(404, { detail: "no such repair of this invoice" }),
      json(422, {
        detail: [{ type: "uuid_parsing", loc: ["path", "repair_id"] }],
      }),
      json(500, {}),
    ];
    stubApi(() => answers.shift() ?? json(500, {}));

    for (const said of [
      "Ova popravka ne postoji, ili faktura nije vaša.",
      "Ova popravka ne postoji, ili faktura nije vaša.",
      "Popravka nije učitana. Pokušajte ponovo malo kasnije.",
    ]) {
      const { unmount } = renderIn(
        "sr-Latn",
        <RepairView invoiceId={ID} repairId={REPAIR} />,
      );
      expect(await screen.findByRole("alert")).toHaveTextContent(said);
      expect(
        screen.getByRole("link", { name: "Nazad na izveštaj" }),
      ).toHaveAttribute("href", `/sr-Latn/invoices/${ID}`);
      unmount();
    }
  });
});
