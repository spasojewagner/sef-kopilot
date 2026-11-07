import { screen } from "@testing-library/react";
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

  it("leads to checking an invoice", () => {
    renderIn("sr-Latn", <HomePage />);

    expect(
      screen.getByRole("link", { name: "Proverite fakturu" }),
    ).toHaveAttribute("href", "/sr-Latn/invoices");
  });

  it("links to the public repository in a new tab", () => {
    renderIn("sr-Latn", <HomePage />);

    const source = screen.getByRole("link", { name: "Izvorni kod na GitHubu" });
    expect(source).toHaveAttribute(
      "href",
      "https://github.com/spasojewagner/sef-kopilot",
    );
    expect(source).toHaveAttribute("target", "_blank");
    expect(source).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(source.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
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
});
