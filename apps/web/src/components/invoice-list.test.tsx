import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { json, keepSession, stubApi } from "@/test/api";
import { invoice } from "@/test/invoices";
import { renderIn } from "@/test/render";

import { InvoiceList } from "./invoice-list";

const navigation = vi.hoisted(() => ({
  replace: vi.fn((url: string) => {
    window.history.replaceState(null, "", url);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }),
}));

vi.mock("next/navigation", async (importOriginal) => {
  const { useSyncExternalStore } = await import("react");
  return {
    ...(await importOriginal<typeof import("next/navigation")>()),
    usePathname: () => window.location.pathname,
    useRouter: () => navigation,
    useSearchParams: () =>
      new URLSearchParams(
        useSyncExternalStore(
          (listener) => {
            window.addEventListener("popstate", listener);
            return () => window.removeEventListener("popstate", listener);
          },
          () => window.location.search,
        ),
      ),
  };
});

const twentyFive = Array.from({ length: 25 }, (_, index) =>
  invoice({ id: `first-${index}` }),
);

beforeEach(() => {
  window.history.replaceState(null, "", "/sr-Latn/invoices");
  navigation.replace.mockClear();
  keepSession();
});

describe("Invoice list", () => {
  it("shows each invoice with what the validator read and its verdict", async () => {
    keepSession();
    stubApi(() =>
      json(200, {
        invoices: [
          invoice(),
          invoice({ id: "c0ffee00-0000-4000-8000-000000000001", valid: true }),
        ],
        next: null,
        total: 2,
      }),
    );

    renderIn("sr-Latn", <InvoiceList />);

    const rows = await screen.findAllByRole("row");
    expect(rows).toHaveLength(3);
    const first = within(rows[1]);
    expect(first.getByRole("link", { name: "F-2026-0042" })).toHaveAttribute(
      "href",
      "/sr-Latn/invoices/0b3f6a2e-1c4d-4e5f-8a9b-0c1d2e3f4a5b",
    );
    expect(first.getByText("Primer d.o.o. → Kupac a.d.")).toBeInTheDocument();
    expect(first.getByText("5. 11. 2026.")).toBeInTheDocument();
    expect(first.getByText("120.000,00 RSD")).toBeInTheDocument();
    expect(first.getByText("Neispravna")).toBeInTheDocument();
    expect(within(rows[2]).getByText("Ispravna")).toBeInTheDocument();
  });

  it("says so of a document that fails the UBL schema", async () => {
    keepSession();
    stubApi(() =>
      json(200, {
        invoices: [invoice({ summary: null })],
        next: null,
        total: 1,
      }),
    );

    renderIn("sr-Latn", <InvoiceList />);

    expect(
      await screen.findByRole("link", { name: "Ne prolazi UBL šemu" }),
    ).toBeInTheDocument();
  });

  it("moves through pages, preserves the previous rows while loading and can go back", async () => {
    let answerNext!: (response: Response) => void;
    const next = new Promise<Response>((resolve) => {
      answerNext = resolve;
    });
    const asked = stubApi(({ search }) =>
      search.includes("after=")
        ? next
        : json(200, { invoices: twentyFive, next: "cursor-1", total: 26 }),
    );
    renderIn("sr-Latn", <InvoiceList />);
    const pages = await screen.findByRole("navigation", { name: "Stranice" });
    expect(within(pages).getByText("1–25 od 26")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("26 faktura");
    const user = userEvent.setup();
    await user.click(within(pages).getByRole("button", { name: "Sledeća" }));

    const previousTable = screen.getByRole("table");
    expect(previousTable.closest("[aria-busy]")).toHaveAttribute(
      "aria-busy",
      "true",
    );
    expect(within(previousTable).getAllByRole("row")).toHaveLength(26);
    answerNext(
      json(200, { invoices: [invoice({ id: "last" })], next: null, total: 26 }),
    );

    expect(await within(pages).findByText("26–26 od 26")).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(2);
    expect(asked.map((request) => request.search)).toEqual([
      "?limit=25",
      "?limit=25&after=cursor-1",
    ]);
    await user.click(within(pages).getByRole("button", { name: "Prethodna" }));
    expect(await within(pages).findByText("1–25 od 26")).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(26);
    expect(
      within(pages).getByRole("button", { name: "Prethodna" }),
    ).toBeDisabled();
  });

  it("reads and writes all filters in the URL and resets pagination on a URL change", async () => {
    window.history.replaceState(
      null,
      "",
      "/en/invoices?q=primer&valid=false&type=CreditNote&from=2026-11-01&to=2026-11-15&size=50",
    );
    const firstPage = Array.from({ length: 50 }, (_, index) =>
      invoice({ id: `first-${index}` }),
    );
    const asked = stubApi(({ search }) =>
      search.includes("after=")
        ? json(200, { invoices: [invoice()], next: null, total: 51 })
        : json(200, { invoices: firstPage, next: "cursor-1", total: 51 }),
    );
    renderIn("en", <InvoiceList />);

    expect(screen.getByRole("searchbox", { name: "Search" })).toHaveValue(
      "primer",
    );
    expect(screen.getByLabelText("Verdict")).toHaveValue("false");
    expect(screen.getByLabelText("Type")).toHaveValue("CreditNote");
    expect(screen.getByLabelText("Issue date from")).toHaveValue("2026-11-01");
    expect(screen.getByLabelText("Issue date to")).toHaveValue("2026-11-15");
    expect(await screen.findByLabelText("Per page")).toHaveValue("50");
    expect(Object.fromEntries(new URLSearchParams(asked[0].search))).toEqual({
      limit: "50",
      q: "primer",
      valid: "false",
      document_type: "CreditNote",
      issued_from: "2026-11-01",
      issued_to: "2026-11-15",
    });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("51–51 of 51")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Verdict"), "true");
    await waitFor(() => expect(asked.at(-1)?.search).toContain("valid=true"));
    expect(asked.at(-1)?.search).not.toContain("after");
    expect(window.location.search).toContain("valid=true");
    expect(window.location.search).toContain("type=CreditNote");
    expect(window.location.search).toContain("size=50");
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
  });

  it("waits 300 ms to search and Escape clears the search", async () => {
    const asked = stubApi(() =>
      json(200, { invoices: [invoice()], next: null, total: 1 }),
    );
    renderIn("sr-Latn", <InvoiceList />);
    await screen.findByText("1 faktura");
    const search = screen.getByRole("searchbox", { name: "Pretraži" });
    vi.useFakeTimers();
    try {
      fireEvent.change(search, { target: { value: "pri" } });
      act(() => vi.advanceTimersByTime(200));
      fireEvent.change(search, { target: { value: "primer" } });
      act(() => vi.advanceTimersByTime(299));
      expect(navigation.replace).not.toHaveBeenCalled();
      act(() => vi.advanceTimersByTime(1));
      expect(navigation.replace).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
    await waitFor(() => expect(asked.at(-1)?.search).toContain("q=primer"));
    fireEvent.keyDown(search, { key: "Escape" });
    expect(search).toHaveValue("");
    expect(window.location.search).toBe("");
    expect(navigation.replace).toHaveBeenCalledTimes(2);
  });

  it("shows the result count politely and marks literal Cyrillic matches in all three fields", async () => {
    window.history.replaceState(null, "", "/sr-Latn/invoices?q=епс.");
    const row = invoice();
    stubApi(() =>
      json(200, {
        invoices: [
          {
            ...row,
            summary: {
              ...row.summary,
              number: "ЕПС.42",
              seller: "Оглед ЕПС.",
              buyer: "Епс. АД",
            },
          },
        ],
        next: null,
        total: 3,
      }),
    );
    renderIn("sr-Latn", <InvoiceList />);

    const count = await screen.findByText("3 fakture");
    expect(count).toHaveAttribute("role", "status");
    expect(count).toHaveAttribute("aria-live", "polite");
    const table = await screen.findByRole("table");
    expect(
      Array.from(table.querySelectorAll("mark"), (mark) => mark.textContent),
    ).toEqual(["ЕПС.", "ЕПС.", "Епс."]);
  });

  it("offers to clear filters when an empty search returns", async () => {
    window.history.replaceState(null, "", "/en/invoices?q=missing");
    stubApi(() => json(200, { invoices: [], next: null, total: 0 }));
    renderIn("en", <InvoiceList />);

    const empty = await screen.findByText("No invoice matches the search.");
    expect(screen.getByRole("status")).toHaveTextContent("0 invoices");
    await userEvent.setup().click(
      within(empty.parentElement!).getByRole("button", {
        name: "Clear filters",
      }),
    );
    expect(window.location.search).toBe("");
    expect(
      await screen.findByText("No invoices yet. Send the first one above."),
    ).toBeInTheDocument();
  });

  it("says when there is none yet", async () => {
    keepSession();
    stubApi(() => json(200, { invoices: [], next: null, total: 0 }));

    renderIn("en", <InvoiceList />);

    const none = await screen.findByText(
      "No invoices yet. Send the first one above.",
    );
    // Beside a mark of its own, which is decoration, and with no table to read.
    expect(none.parentElement?.querySelector("svg")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("says when the list could not be loaded", async () => {
    keepSession();
    stubApi(() => json(500, { detail: "Internal Server Error" }));

    renderIn("sr-Latn", <InvoiceList />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Fakture nisu učitane.",
    );
  });
});
