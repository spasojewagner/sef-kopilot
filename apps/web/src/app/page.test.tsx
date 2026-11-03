import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Home from "./page";

describe("Home page", () => {
  it("shows the product name, the status badge and the non-affiliation notice", () => {
    render(<Home />);

    expect(
      screen.getByRole("heading", { level: 1, name: "SEF Kopilot" }),
    ).toBeInTheDocument();
    expect(screen.getByText("pre-alpha")).toBeInTheDocument();
    expect(
      screen.getByText(/nije sertifikovani validator/i),
    ).toBeInTheDocument();
  });

  it("links to the public repository in a new tab", () => {
    render(<Home />);

    const link = screen.getByRole("link", { name: /github/i });
    expect(link).toHaveAttribute(
      "href",
      "https://github.com/spasojewagner/sef-kopilot",
    );
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
  });
});
