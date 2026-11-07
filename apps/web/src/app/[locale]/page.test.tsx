import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderIn } from "@/test/render";

import HomePage from "./page";

describe("Home page", () => {
  it("says what the product does, and that it is pre-alpha, in Serbian (Latin)", () => {
    renderIn("sr-Latn", <HomePage />);

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: "Proverite e-fakturu pre nego što je pošaljete na SEF",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(/proverava UBL fakturu/)).toBeInTheDocument();
    expect(screen.getByText(/u fazi pre-alpha/)).toBeInTheDocument();
  });

  it("says the same in English", () => {
    renderIn("en", <HomePage />);

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: "Check an e-invoice before you send it to SEF",
      }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/proverava/)).not.toBeInTheDocument();
  });

  it("leads to checking an invoice, by one link of that name", () => {
    renderIn("sr-Latn", <HomePage />);

    expect(
      screen.getByRole("link", { name: "Proverite fakturu" }),
    ).toHaveAttribute("href", "/sr-Latn/invoices");
    expect(
      screen.getByRole("link", { name: "Počnite proveru" }),
    ).toHaveAttribute("href", "/sr-Latn/invoices");
  });

  it("links to the public repository and its synthetic invoices in new tabs", () => {
    renderIn("sr-Latn", <HomePage />);

    const source = screen.getByRole("link", { name: "Izvorni kod na GitHubu" });
    expect(source).toHaveAttribute(
      "href",
      "https://github.com/spasojewagner/sef-kopilot",
    );
    const examples = screen.getByRole("link", { name: "Primeri faktura" });
    expect(examples).toHaveAttribute(
      "href",
      "https://github.com/spasojewagner/sef-kopilot/tree/main/fixtures/invoices/synthetic",
    );
    for (const link of [source, examples]) {
      expect(link).toHaveAttribute("target", "_blank");
      expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
      expect(link.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    }
  });

  it("shows an example of a report, which a screen reader reads as its caption", () => {
    renderIn("sr-Latn", <HomePage />);

    const example = screen.getByRole("figure", {
      name: /faktura sa šifrom vrste 393 krši pravilo SRB-001/,
    });
    const drawing = example.querySelector("[aria-hidden='true']");
    expect(drawing).toHaveTextContent("RF-2026-000123");
    expect(drawing).toHaveTextContent("SRB-001");
    expect(drawing).toHaveTextContent("393 → 380");
  });

  it("walks an invoice's course in four steps, in order", () => {
    renderIn("en", <HomePage />);

    const route = screen.getByRole("region", {
      name: "The model suggests, the validator judges, you decide",
    });
    const steps = within(within(route).getByRole("list")).getAllByRole(
      "listitem",
    );
    expect(
      steps.map(
        (step) => within(step).getByRole("heading", { level: 3 }).textContent,
      ),
    ).toEqual([
      "Validation",
      "Explanation",
      "Proposed repair",
      "Your decision",
    ]);
  });

  it("names the rules it checks against", () => {
    renderIn("sr-Latn", <HomePage />);

    const standards = screen.getByRole("region", {
      name: "Pravila po kojima se proverava",
    });
    expect(
      within(standards)
        .getAllByRole("term")
        .map((term) => term.textContent),
    ).toEqual([
      "UBL 2.1",
      "EN 16931",
      "SRB-CIUS",
      "Peppol BIS Billing 3.0",
      "Računske provere",
    ]);
  });

  it("shows the API and the MCP server at the address this build talks to", () => {
    renderIn("en", <HomePage />);

    const developers = screen.getByRole("region", {
      name: "The same without the page: an HTTP API and MCP",
    });
    expect(developers).toHaveTextContent("API=http://127.0.0.1:8000");
    expect(developers).toHaveTextContent(
      'curl "$API/invoices/validate?profile=srb"',
    );
    expect(developers).toHaveTextContent("--data-binary @invoice.xml");
    expect(developers).toHaveTextContent("POST http://127.0.0.1:8000/mcp");
    expect(developers).toHaveTextContent('"name": "validate_invoice"');
    expect(
      within(developers).getByRole("link", {
        name: "The API's documentation",
      }),
    ).toHaveAttribute("href", "http://127.0.0.1:8000/docs");
  });
});
