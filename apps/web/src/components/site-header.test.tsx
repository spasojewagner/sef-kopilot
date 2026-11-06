import { screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderIn } from "@/test/intl";

import { SiteHeader } from "./site-header";

vi.mock("next/navigation", async (importOriginal) => ({
  ...(await importOriginal<typeof import("next/navigation")>()),
  usePathname: () => "/sr-Latn/invoices",
}));

describe("Site header", () => {
  it("leads to the home page in the visitor's language", () => {
    renderIn("en", <SiteHeader />);

    const banner = screen.getByRole("banner");
    expect(
      within(banner).getByRole("link", { name: "SEF Kopilot" }),
    ).toHaveAttribute("href", "/en");
  });

  it("offers the page in the other language", () => {
    renderIn("sr-Latn", <SiteHeader />);

    const languages = within(screen.getByRole("banner")).getByRole(
      "navigation",
      { name: "Jezik" },
    );
    expect(
      within(languages).getByRole("link", { name: "English" }),
    ).toHaveAttribute("href", "/en/invoices");
  });
});
