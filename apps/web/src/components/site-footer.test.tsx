import { screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderIn } from "@/test/render";

import { SiteFooter } from "./site-footer";

vi.mock("next/navigation", async (importOriginal) => ({
  ...(await importOriginal<typeof import("next/navigation")>()),
  usePathname: () => "/sr-Latn/invoices",
}));

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

  it("offers the page in the other language, for a phone's header has no room for it", () => {
    renderIn("sr-Latn", <SiteFooter />);

    const languages = within(screen.getByRole("contentinfo")).getByRole(
      "navigation",
      { name: "Jezik" },
    );
    expect(
      within(languages).getByRole("link", { name: "English" }),
    ).toHaveAttribute("href", "/en/invoices");
    // Below 640 px only: wider screens have them in the header.
    expect(languages.parentElement).toHaveClass("sm:hidden");
  });
});
