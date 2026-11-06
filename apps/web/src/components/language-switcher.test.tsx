import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderIn } from "@/test/intl";

import { LanguageSwitcher } from "./language-switcher";

const pathname = vi.hoisted(() => ({ current: "/sr-Latn" }));

vi.mock("next/navigation", async (importOriginal) => ({
  ...(await importOriginal<typeof import("next/navigation")>()),
  usePathname: () => pathname.current,
}));

describe("Language switcher", () => {
  beforeEach(() => {
    pathname.current = "/sr-Latn";
  });

  it("links to the same page in each language, each named in its own", () => {
    pathname.current = "/sr-Latn/invoices";

    renderIn("sr-Latn", <LanguageSwitcher />);

    const languages = screen.getByRole("navigation", { name: "Jezik" });
    const links = within(languages).getAllByRole("link");
    expect(
      links.map((link) => [link.textContent, link.getAttribute("href")]),
    ).toEqual([
      ["Srpski", "/sr-Latn/invoices"],
      ["English", "/en/invoices"],
    ]);
    expect(links.map((link) => link.getAttribute("lang"))).toEqual([
      "sr-Latn",
      "en",
    ]);
  });

  it("marks the language of the page", () => {
    pathname.current = "/en";

    renderIn("en", <LanguageSwitcher />);

    expect(
      screen.getByRole("navigation", { name: "Language" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "English" })).toHaveAttribute(
      "aria-current",
      "true",
    );
    expect(screen.getByRole("link", { name: "Srpski" })).not.toHaveAttribute(
      "aria-current",
    );
  });
});
