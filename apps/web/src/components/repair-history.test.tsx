import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { json, keepSession, stubApi } from "@/test/api";
import { storedInvoice, stubReportApi } from "@/test/invoices";
import { listedRepair } from "@/test/repairs";
import { renderIn } from "@/test/render";

import { RepairHistory } from "./repair-history";

const ID = storedInvoice().id;

describe("The repairs of an invoice", () => {
  it("are listed the latest first: who proposed each, where it stands, what it leaves", async () => {
    keepSession();
    stubReportApi({
      repairs: [
        listedRepair({
          id: "r-3",
          model: "openai/gpt-oss-120b",
          applied: 2,
          needs_decision: 1,
          failed: 0,
        }),
        listedRepair({
          id: "r-2",
          status: "rejected",
          proposed_by: "u-bob",
          proposed_at: "2026-11-05T09:00:00Z",
          decided_at: "2026-11-05T10:00:00Z",
          valid: false,
        }),
        listedRepair({
          id: "r-1",
          status: "superseded",
          proposed_by: null,
          proposed_with_key: true,
        }),
        listedRepair({ id: "r-0", status: "approved", proposed_by: null }),
      ],
    });

    renderIn("sr-Latn", <RepairHistory invoiceId={ID} />);

    const rows = (await screen.findAllByRole("row")).slice(1);
    expect(
      rows.map((row) =>
        within(row)
          .getAllByRole("cell")
          .map((cell) => cell.textContent),
      ),
    ).toEqual([
      [
        "6. 11. 2026. 11:30",
        "vi, uz jezički model openai/gpt-oss-120b",
        "Čeka odluku",
        "Ispravna",
        "primenjeno 2, čeka odluku 1, nije primenjeno 0",
      ],
      [
        "5. 11. 2026. 10:00",
        "drugi član",
        "Odbijena",
        "Neispravna",
        "primenjeno 1, čeka odluku 1, nije primenjeno 1",
      ],
      [
        "6. 11. 2026. 11:30",
        "API ključ",
        "Zastarela",
        "Ispravna",
        "primenjeno 1, čeka odluku 1, nije primenjeno 1",
      ],
      [
        "6. 11. 2026. 11:30",
        "bivši član",
        "Odobrena",
        "Ispravna",
        "primenjeno 1, čeka odluku 1, nije primenjeno 1",
      ],
    ]);
    expect(
      within(rows[0]).getByRole("link", { name: "6. 11. 2026. 11:30" }),
    ).toHaveAttribute("href", `/sr-Latn/invoices/${ID}/repairs/r-3`);
  });

  it("say so when there are none", async () => {
    keepSession();
    stubReportApi();

    renderIn("sr-Latn", <RepairHistory invoiceId={ID} />);

    expect(
      await screen.findByText("Ova faktura još nema predloženih popravki."),
    ).toBeInTheDocument();
  });

  it("say so when they could not be loaded", async () => {
    keepSession();
    stubApi(() => json(500, { detail: "the database is not reachable" }));

    renderIn("en", <RepairHistory invoiceId={ID} />);

    expect(
      await screen.findByText(
        "The repairs did not load. Try again a little later.",
      ),
    ).toBeInTheDocument();
  });
});
