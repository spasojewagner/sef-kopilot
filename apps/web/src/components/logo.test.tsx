import { readFileSync } from "node:fs";
import path from "node:path";

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Logo, LogoMark, MARK } from "./logo";

const FAVICON = readFileSync(
  path.join(import.meta.dirname, "../app/icon.svg"),
  "utf8",
);

/** The value of each `attribute` the favicon's markup gives, in order. */
function favicon(attribute: string): string[] {
  return [...FAVICON.matchAll(new RegExp(` ${attribute}="([^"]*)"`, "g"))].map(
    (match) => match[1],
  );
}

describe("Logo", () => {
  it("is the product's name, its mark hidden from screen readers", () => {
    const { container } = render(<Logo name="SEF Kopilot" />);

    expect(screen.getByText("SEF Kopilot")).toBeInTheDocument();
    expect(container.querySelector("svg")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("names itself when its mark stands alone", () => {
    render(<LogoMark label="SEF Kopilot" />);

    expect(
      screen.getByRole("img", { name: "SEF Kopilot" }),
    ).toBeInTheDocument();
  });

  it("draws the favicon's mark, in the colours of the page around it", () => {
    const { container } = render(<LogoMark />);

    const paths = [...container.querySelectorAll("path")].map((path) =>
      path.getAttribute("d"),
    );
    expect(paths).toEqual(favicon("d"));
    expect(paths).toEqual([MARK.ring, MARK.arm, MARK.needle]);
    const joint = container.querySelector("circle");
    expect([
      joint?.getAttribute("cx"),
      joint?.getAttribute("cy"),
      joint?.getAttribute("r"),
    ]).toEqual([...favicon("cx"), ...favicon("cy"), ...favicon("r")]);
    expect(container.querySelector("path")).toHaveAttribute(
      "stroke",
      "currentColor",
    );
    expect(container.querySelector("g")).toHaveClass("fill-brand");
  });
});
