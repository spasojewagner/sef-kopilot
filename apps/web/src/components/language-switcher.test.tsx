import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderIn } from "@/test/render";

import { LanguageSwitcher, Languages } from "./language-switcher";

/** The page's path; none while it is not known yet, as when the page is built. */
const pathname = vi.hoisted(() => ({ current: "/sr-Latn" as string | null }));

vi.mock("next/navigation", async (importOriginal) => ({
  ...(await importOriginal<typeof import("next/navigation")>()),
  usePathname: () => {
    if (pathname.current === null) {
      // Rendering waits for the path, as it does where the path is known only when asked for.
      throw new Promise(() => {});
    }
    return pathname.current;
  },
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

  it("keeps the links' place, neither seen nor read, until the page's path is known", () => {
    pathname.current = null;

    renderIn("sr-Latn", <Languages />);

    const place = screen.getByText("Srpski").closest("ul") as HTMLElement;
    expect(place).toHaveAttribute("aria-hidden", "true");
    expect(place).toHaveClass("invisible");
    expect(place.textContent).toBe("SrpskiEnglish");
    expect(screen.queryAllByRole("link", { hidden: true })).toEqual([]);
  });
});
