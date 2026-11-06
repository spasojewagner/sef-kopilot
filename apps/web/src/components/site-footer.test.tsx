import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderIn } from "@/test/render";

import { SiteFooter } from "./site-footer";

describe("Site footer", () => {
  it("says that the project is not a certified validator, in Serbian (Latin)", () => {
    renderIn("sr-Latn", <SiteFooter />);

    expect(
      within(screen.getByRole("contentinfo")).getByText(
        /Nije sertifikovani validator/,
      ),
    ).toBeInTheDocument();
  });

  it("says the same in English", () => {
    renderIn("en", <SiteFooter />);

    expect(
      within(screen.getByRole("contentinfo")).getByText(
        /It is not a certified validator/,
      ),
    ).toBeInTheDocument();
  });
});
