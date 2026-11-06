import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderIn } from "@/test/intl";

import HomePage from "./page";

describe("Home page", () => {
  it("shows the product name, its status and what it does, in Serbian (Latin)", () => {
    renderIn("sr-Latn", <HomePage />);

    expect(
      screen.getByRole("heading", { level: 1, name: "SEF Kopilot" }),
    ).toBeInTheDocument();
    expect(screen.getByText("pre-alpha")).toBeInTheDocument();
    expect(screen.getByText(/Deterministička validacija/)).toBeInTheDocument();
  });

  it("says the same in English", () => {
    renderIn("en", <HomePage />);

    expect(
      screen.getByText(/Deterministic validation, plain-language/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Deterministička/)).not.toBeInTheDocument();
  });

  it("links to the public repository in a new tab", () => {
    renderIn("sr-Latn", <HomePage />);

    const link = screen.getByRole("link", { name: "Izvorni kod na GitHubu" });
    expect(link).toHaveAttribute(
      "href",
      "https://github.com/spasojewagner/sef-kopilot",
    );
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
  });

  it("draws the link as a button, its arrow hidden from screen readers", () => {
    renderIn("en", <HomePage />);

    const link = screen.getByRole("link", { name: "Source code on GitHub" });
    expect(link).toHaveAttribute("data-slot", "button");
    expect(link.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });
});
