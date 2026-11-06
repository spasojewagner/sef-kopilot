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
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
  });
});
