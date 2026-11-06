import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderIn } from "@/test/intl";

import NotFound from "./not-found";

describe("Page not found", () => {
  it("says so and leads home, in the visitor's language", () => {
    renderIn("sr-Latn", <NotFound />);

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: "Ova stranica ne postoji",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Na početnu stranu" }),
    ).toHaveAttribute("href", "/sr-Latn");
  });

  it("says the same in English", () => {
    renderIn("en", <NotFound />);

    expect(
      screen.getByRole("link", { name: "Back to the home page" }),
    ).toHaveAttribute("href", "/en");
  });
});
