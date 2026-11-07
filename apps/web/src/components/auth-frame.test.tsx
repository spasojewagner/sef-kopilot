import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderIn } from "@/test/render";

import { AuthFrame } from "./auth-frame";

describe("The frame of signing in", () => {
  it("holds the form, beside what the product holds to", () => {
    renderIn(
      "sr-Latn",
      <AuthFrame>
        <form aria-label="Prijava" />
      </AuthFrame>,
    );

    expect(screen.getByRole("form", { name: "Prijava" })).toBeInTheDocument();
    const brand = screen.getByRole("complementary");
    expect(brand).toHaveTextContent(
      "Model predlaže, validator sudi, vi odlučujete",
    );
    // The mark beside the words is decoration, and the chart behind them too.
    expect(brand.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    expect(brand.querySelector("img")).toHaveAttribute("alt", "");
  });

  it("shows the brand beside the form on a wide screen only", () => {
    renderIn("en", <AuthFrame>{null}</AuthFrame>);

    expect(screen.getByRole("complementary")).toHaveClass("hidden", "lg:flex");
  });
});
