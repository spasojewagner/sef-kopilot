import { screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { STORAGE_KEY } from "@/lib/session";
import { renderIn } from "@/test/render";

import { currentness, Sections } from "./sections";

const navigation = vi.hoisted(() => ({ pathname: "/sr-Latn/invoices" }));

vi.mock("next/navigation", async (importOriginal) => ({
  ...(await importOriginal<typeof import("next/navigation")>()),
  usePathname: () => navigation.pathname,
}));

/** A member of Primer d.o.o., signed in in this browser. */
function signIn() {
  localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({
      refreshToken: "refresh-1",
      refreshExpiresAt: Date.now() + 3_600_000,
      identity: {
        user: { id: "u-alice", email: "alice@primer.example" },
        organization: { id: "o-primer", name: "Primer d.o.o." },
        role: "owner",
      },
    }),
  );
}

describe("Sections in the header", () => {
  it("are not there for a visitor who is not signed in", () => {
    renderIn("sr-Latn", <Sections />);

    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });

  it("lead a member to the invoices and the organization, in their language", () => {
    signIn();
    navigation.pathname = "/en/organization";
    renderIn("en", <Sections />);

    const sections = screen.getByRole("navigation", { name: "Sections" });
    expect(
      within(sections).getByRole("link", { name: "Invoices" }),
    ).toHaveAttribute("href", "/en/invoices");
    // On a phone an icon, named for a screen reader by the text a wider screen shows.
    expect(
      within(sections).getByRole("link", { name: "Organization" }),
    ).toHaveAttribute("href", "/en/organization");
  });

  it("mark the section of the page, and its page as the page itself", () => {
    signIn();
    navigation.pathname = "/sr-Latn/invoices";
    renderIn("sr-Latn", <Sections />);

    expect(screen.getByRole("link", { name: "Fakture" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(
      screen.getByRole("link", { name: "Organizacija" }),
    ).not.toHaveAttribute("aria-current");
  });

  it("mark the section of a page within it", () => {
    signIn();
    navigation.pathname = "/sr-Latn/invoices/0b5c-report";
    renderIn("sr-Latn", <Sections />);

    expect(screen.getByRole("link", { name: "Fakture" })).toHaveAttribute(
      "aria-current",
      "true",
    );
  });
});

describe("Where a page stands among the sections", () => {
  it.each([
    ["/invoices", "page"],
    ["/invoices/42", "true"],
    ["/invoices/42/repairs/7", "true"],
    ["/invoicesx", undefined],
    ["/", undefined],
    ["/organization", undefined],
  ])("%s is %s for the invoices", (pathname, expected) => {
    expect(currentness(pathname, "/invoices")).toBe(expected);
  });
});
