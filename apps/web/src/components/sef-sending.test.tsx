import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { StoredInvoice } from "@/lib/invoices";
import type { Submission } from "@/lib/sef";
import { ALICE, type Asked, aMoment, json, keepSession } from "@/test/api";
import { storedInvoice, stubReportApi } from "@/test/invoices";
import { renderIn } from "@/test/render";

import { InvoiceReport } from "./invoice-report";

// The report offers the model's repair, which opens the repair's page when it is written.
vi.mock("next/navigation", async (importOriginal) => ({
  ...(await importOriginal<typeof import("next/navigation")>()),
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
  }),
}));

const ID = "0b3f6a2e-1c4d-4e5f-8a9b-0c1d2e3f4a5b";
const SEF_PATH = `/invoices/${ID}/sef`;

/** An invoice the validator passes. */
function valid(): StoredInvoice {
  const stored = storedInvoice();
  return {
    ...stored,
    valid: true,
    report: { ...stored.report, valid: true, violations: [] },
  };
}

/** A submission of the invoice, imported unless ``changes`` say otherwise. */
function submission(changes: Partial<Submission> = {}): Submission {
  return {
    id: "5e0d1c2b-3a49-4857-a6b5-c4d3e2f1a0b9",
    invoice_id: ID,
    state: "imported",
    sales_invoice_id: 4711,
    sef_invoice_id: 815,
    sef_status: null,
    refusal: null,
    detail: null,
    attempts: 1,
    sent_at: "2026-11-09T12:04:58Z",
    answered_at: "2026-11-09T12:05:00Z",
    checked_at: null,
    ...changes,
  };
}

/**
 * The report's API, for Alice as ``role`` in Primer, which has a key to SEF unless ``key`` is
 * false; sending is answered by ``send``.
 */
function api({
  role = "accountant",
  stored = valid(),
  submissions = [],
  key = true,
  send = () => json(201, submission()),
}: {
  role?: string;
  stored?: StoredInvoice;
  submissions?: Submission[];
  key?: boolean;
  send?: (asked: Asked) => Response | Promise<Response>;
} = {}): Asked[] {
  return stubReportApi({
    stored,
    submissions,
    other: (asked) => {
      if (asked.path === "/auth/me") {
        return json(200, { ...ALICE, role });
      }
      if (asked.path === "/organization") {
        return json(200, {
          id: "o-primer",
          name: "Primer d.o.o.",
          invoice_retention_days: null,
          sef_key_set_at: key ? "2026-11-08T21:40:00Z" : null,
        });
      }
      if (asked.path === SEF_PATH && asked.method === "POST") {
        return send(asked);
      }
      return json(404, { detail: "not found" });
    },
  });
}

const posts = (asked: Asked[]) =>
  asked.filter((r) => r.method === "POST" && r.path === SEF_PATH).length;

const user = () => userEvent.setup();

async function sefSection(): Promise<ReturnType<typeof within>> {
  const heading = await screen.findByRole("heading", { level: 2, name: "SEF" });
  return within(heading.closest("section") as HTMLElement);
}

async function press(name: string) {
  await user().click(screen.getByRole("button", { name }));
}

describe("The invoice and SEF", () => {
  it("shows a member where a sent invoice stands in SEF, with the buyer's comment", async () => {
    keepSession();
    api({
      role: "client",
      submissions: [
        submission({
          sef_status: "Rejected",
          detail: "Pogrešan iznos",
          checked_at: "2026-11-09T12:20:00Z",
        }),
      ],
    });

    renderIn("sr-Latn", <InvoiceReport id={ID} />);

    const sef = await sefSection();
    expect(
      await sef.findByText("SEF je uvezao fakturu 9. 11. 2026. 13:05."),
    ).toBeInTheDocument();
    expect(sef.getByText("Na SEF-u: kupac ju je odbio.")).toBeInTheDocument();
    expect(sef.getByText("Komentar kupca: Pogrešan iznos")).toBeInTheDocument();
    expect(
      sef.getByText(
        "ID prodajne fakture na SEF-u: 4711. SEF je poslednji put pitan 9. 11. 2026. 13:20.",
      ),
    ).toBeInTheDocument();
    // Imported, it is not sent again, by anyone.
    expect(sef.queryByRole("button")).not.toBeInTheDocument();
  });

  it("tells a client of the office who sends, and offers them nothing", async () => {
    keepSession();
    const asked = api({ role: "client" });

    renderIn("sr-Latn", <InvoiceReport id={ID} />);

    const sef = await sefSection();
    expect(
      await sef.findByText(
        "Na SEF fakture šalju vlasnik i računovođa organizacije.",
      ),
    ).toBeInTheDocument();
    expect(sef.getByText("Faktura nije slata na SEF.")).toBeInTheDocument();
    expect(sef.queryByRole("button")).not.toBeInTheDocument();
    await aMoment();
    expect(asked.some((r) => r.path === "/organization")).toBe(false);
  });

  it("sends a valid invoice only after a second press that names the organization", async () => {
    keepSession();
    const asked = api();
    renderIn("sr-Latn", <InvoiceReport id={ID} />);
    const sef = await sefSection();

    await user().click(
      await sef.findByRole("button", { name: "Pošalji na SEF" }),
    );
    expect(
      sef.getByText(
        "Faktura F-2026-0042 ide na SEF demo u ime organizacije Primer d.o.o.: SEF je čuva, a kupac je vidi. Poslati je?",
      ),
    ).toBeInTheDocument();
    // The keyboard's focus follows the question, and comes back when it is cancelled.
    expect(sef.getByRole("button", { name: "Da, pošalji" })).toHaveFocus();
    await press("Odustani");
    expect(sef.getByRole("button", { name: "Pošalji na SEF" })).toHaveFocus();
    expect(posts(asked)).toBe(0);

    await press("Pošalji na SEF");
    await press("Da, pošalji");

    expect(await sef.findByRole("status")).toHaveTextContent(
      "SEF je uvezao fakturu.",
    );
    expect(posts(asked)).toBe(1);
    expect(
      sef.getByText("SEF je uvezao fakturu 9. 11. 2026. 13:05."),
    ).toBeInTheDocument();
    expect(
      sef.getByText(
        "SEF još nije pitan gde je faktura: SEF Kopilot ga pita u narednim minutima.",
      ),
    ).toBeInTheDocument();
    expect(
      sef.queryByRole("button", { name: "Pošalji na SEF" }),
    ).not.toBeInTheDocument();
  });

  it("waits for SEF as long as the API may try it", async () => {
    // The API asks SEF up to three times, each for up to half a minute.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      keepSession();
      api({
        // As a browser's fetch does, the request ends when the page gives up on it.
        send: ({ signal }) =>
          new Promise((answer, fail) => {
            const timer = setTimeout(
              () => answer(json(201, submission())),
              95_000,
            );
            signal?.addEventListener("abort", () => {
              clearTimeout(timer);
              fail(signal.reason);
            });
          }),
      });
      renderIn("sr-Latn", <InvoiceReport id={ID} />);
      const sef = await sefSection();
      await user().click(
        await sef.findByRole("button", { name: "Pošalji na SEF" }),
      );
      await press("Da, pošalji");

      await vi.advanceTimersByTimeAsync(96_000);

      expect(await sef.findByRole("status")).toHaveTextContent(
        "SEF je uvezao fakturu.",
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not offer to send an invoice the validator does not pass", async () => {
    keepSession();
    const asked = api({ role: "owner", stored: storedInvoice() });

    renderIn("sr-Latn", <InvoiceReport id={ID} />);

    const sef = await sefSection();
    expect(
      await sef.findByText(
        "Na SEF se šalje samo faktura koju validator propušta. Ova to nije: popravite je, pa je pošaljite.",
      ),
    ).toBeInTheDocument();
    expect(
      sef.queryByRole("button", { name: "Pošalji na SEF" }),
    ).not.toBeInTheDocument();
    await aMoment();
    expect(asked.some((r) => r.path === "/organization")).toBe(false);
  });

  it("says where the owner sets a key, when the organization has none", async () => {
    keepSession();
    api({ key: false });

    renderIn("sr-Latn", <InvoiceReport id={ID} />);

    const sef = await sefSection();
    expect(
      await sef.findByText(/Organizacija nema ključ za SEF/),
    ).toHaveTextContent(
      "Organizacija nema ključ za SEF. Vlasnik ga postavlja na stranici organizacije.",
    );
    expect(
      sef.getByRole("link", { name: "stranici organizacije" }),
    ).toHaveAttribute("href", "/sr-Latn/organization");
    expect(sef.queryByRole("button")).not.toBeInTheDocument();
  });

  it("offers to send again when SEF did not answer, which asks with the same request id", async () => {
    keepSession();
    const unanswered = submission({
      state: "unconfirmed",
      sales_invoice_id: null,
      sef_invoice_id: null,
      answered_at: null,
    });
    const asked = api({ submissions: [unanswered] });
    renderIn("en", <InvoiceReport id={ID} />);
    const sef = await sefSection();

    expect(
      await sef.findByText(
        "The invoice was sent on Nov 9, 2026, 1:04 PM, but SEF's answer did not come.",
      ),
    ).toBeInTheDocument();
    expect(
      sef.getByText(
        "Sent again, the invoice carries the same request id, so SEF imports it only once.",
      ),
    ).toBeInTheDocument();
    await press("Send again");
    await press("Yes, send it");

    expect(await sef.findByRole("status")).toHaveTextContent(
      "SEF imported the invoice.",
    );
    expect(posts(asked)).toBe(1);
    // The same submission, answered: nothing listed as sent before.
    expect(sef.queryByText("Sent before")).not.toBeInTheDocument();
  });

  it("shows SEF's refusal in SEF's words, and sends the invoice again as a new submission", async () => {
    keepSession();
    const refused = submission({
      id: "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d",
      state: "refused",
      sales_invoice_id: null,
      sef_invoice_id: null,
      refusal: "invoice",
      detail: "Neispravan PIB kupca",
      sent_at: "2026-11-09T11:00:00Z",
      answered_at: "2026-11-09T11:00:02Z",
    });
    api({ role: "owner", submissions: [refused] });
    renderIn("sr-Latn", <InvoiceReport id={ID} />);
    const sef = await sefSection();

    expect(
      await sef.findByText("SEF nije uvezao fakturu 9. 11. 2026. 12:00."),
    ).toBeInTheDocument();
    expect(sef.getByText("SEF: Neispravan PIB kupca")).toBeInTheDocument();
    await press("Pošalji na SEF");
    await press("Da, pošalji");

    expect(await sef.findByRole("status")).toHaveTextContent(
      "SEF je uvezao fakturu.",
    );
    expect(sef.getByText("Ranija slanja")).toBeInTheDocument();
    expect(
      sef.getByText("9. 11. 2026. 12:00: nije uvezena"),
    ).toBeInTheDocument();
  });

  it("says that SEF refused the organization's key", async () => {
    keepSession();
    api({
      submissions: [
        submission({
          state: "refused",
          refusal: "key",
          sales_invoice_id: null,
          sef_invoice_id: null,
        }),
      ],
    });

    renderIn("sr-Latn", <InvoiceReport id={ID} />);

    expect(
      await screen.findByText(
        "SEF je odbio ključ organizacije 9. 11. 2026. 13:05: vlasnik treba da postavi važeći ključ.",
      ),
    ).toBeInTheDocument();
  });

  it.each([
    [
      json(409, { detail: "imported", reason: "sent" }),
      "Faktura nije poslata ponovo: SEF ju je već uvezao.",
      SEF_PATH,
    ],
    [
      json(409, { detail: "no key", reason: "no-key" }),
      "Faktura nije poslata: organizacija nema ključ za SEF.",
      "/organization",
    ],
    [
      json(409, { detail: "invalid", reason: "invalid" }),
      "Faktura nije poslata: validator je ne propušta po SRB-CIUS, profilu SEF-a.",
      `/invoices/${ID}`,
    ],
    [
      json(503, { detail: "busy" }),
      "Faktura nije poslata: validator je zauzet ili ključ organizacije ne može da se koristi na ovom serveru. Pokušajte malo kasnije.",
      SEF_PATH,
    ],
    [
      json(502, { detail: "bad gateway" }),
      "API nije dao jasan odgovor. Slanja su ponovo pročitana: proverite ih pre nego što pošaljete ponovo.",
      SEF_PATH,
    ],
  ])(
    "says why nothing was sent, and reads again what it names (%#)",
    async (answer, message, readAgain) => {
      keepSession();
      const asked = api({ send: () => answer.clone() });
      renderIn("sr-Latn", <InvoiceReport id={ID} />);
      const sef = await sefSection();

      await user().click(
        await sef.findByRole("button", { name: "Pošalji na SEF" }),
      );
      const before = asked.filter(
        (r) => r.method === "GET" && r.path === readAgain,
      ).length;
      await press("Da, pošalji");

      expect(await sef.findByRole("alert")).toHaveTextContent(message);
      await waitFor(() =>
        expect(
          asked.filter((r) => r.method === "GET" && r.path === readAgain)
            .length,
        ).toBeGreaterThan(before),
      );
    },
  );
});
