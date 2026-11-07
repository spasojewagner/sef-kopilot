import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import {
  invoiceQuery,
  invoicesQuery,
  repairQuery,
  repairsQuery,
} from "@/lib/queries";
import type { Repair } from "@/lib/repairs";
import { aMoment, type Asked, json, keepSession, stubApi } from "@/test/api";
import { storedInvoice } from "@/test/invoices";
import { listedRepair, repair } from "@/test/repairs";
import { renderIn, testQueryClient } from "@/test/render";

import { RepairView } from "./repair-view";

const ID = storedInvoice().id;
const REPAIR = repair().id;
const PATH = `/invoices/${ID}/repairs/${REPAIR}`;
const DECIDED = { decided_by: "u-alice", decided_at: "2026-11-06T12:00:00Z" };

/**
 * An API that has ``shown`` as the repair, read again as ``again`` after a decision when that
 * is given, and answers the decisions with ``decided``.
 */
function api(
  decided: (asked: Asked) => Response | Promise<Response>,
  shown: Repair = repair(),
  again: Repair = shown,
): Asked[] {
  let reads = 0;
  return stubApi((asked) => {
    if (asked.method === "GET" && asked.path === PATH) {
      reads += 1;
      return json(200, reads === 1 ? shown : again);
    }
    return decided(asked);
  });
}

const decisions = (asked: Asked[]) =>
  asked.filter((request) => request.method === "POST").map((r) => r.path);
const reads = (asked: Asked[]) =>
  asked.filter((request) => request.method === "GET" && request.path === PATH)
    .length;

async function press(name: string) {
  await userEvent.setup().click(screen.getByRole("button", { name }));
}

async function decision() {
  const heading = await screen.findByRole("heading", {
    level: 2,
    name: "Odluka",
  });
  return within(heading.closest("section") as HTMLElement);
}

describe("A person's decision on a repair", () => {
  it("approves it only after a second press that says what approval does", async () => {
    keepSession();
    const asked = api(() =>
      json(200, repair({ status: "approved", ...DECIDED })),
    );
    const client = testQueryClient();
    client.setQueryData(invoiceQuery(ID).queryKey, storedInvoice());
    client.setQueryData(repairsQuery(ID).queryKey, [listedRepair()]);
    client.setQueryData(invoicesQuery.queryKey, {
      pages: [{ invoices: [], next: null }],
      pageParams: [null],
    });
    renderIn(
      "sr-Latn",
      <RepairView invoiceId={ID} repairId={REPAIR} />,
      client,
    );

    const section = await decision();
    expect(
      section.getByText(/^Odobrena popravka menja fakturu/),
    ).toBeInTheDocument();
    await press("Odobri");
    expect(
      section.getByText(
        "Faktura će biti zamenjena kopijom sa ovim izmenama. Odobravate popravku?",
      ),
    ).toBeInTheDocument();
    // The keyboard's focus follows the question, and comes back when it is cancelled.
    expect(screen.getByRole("button", { name: "Da, odobri" })).toHaveFocus();
    await press("Odustani");
    expect(screen.getByRole("button", { name: "Odobri" })).toHaveFocus();
    await press("Odobri");
    expect(decisions(asked)).toEqual([]);
    await press("Da, odobri");

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Popravka je odobrena: faktura je sada kopija sa ovim izmenama.",
    );
    expect(decisions(asked)).toEqual([`${PATH}/approval`]);
    // The page shows the decided repair, kept fresh; what the approval changed is read again.
    expect(screen.getByText("Odobrena")).toBeInTheDocument();
    expect(screen.getByText("vi, 6. 11. 2026. 13:00")).toBeInTheDocument();
    expect(reads(asked)).toBe(1);
    const stale = (key: readonly unknown[]) =>
      client.getQueryState(key)?.isInvalidated;
    expect(stale(repairQuery(ID, REPAIR).queryKey)).toBe(false);
    expect(stale(invoiceQuery(ID).queryKey)).toBe(true);
    expect(stale(repairsQuery(ID).queryKey)).toBe(true);
    expect(stale(invoicesQuery.queryKey)).toBe(true);
  });

  it("rejects it at once, which leaves the invoice as it was", async () => {
    keepSession();
    const asked = api(() =>
      json(200, repair({ status: "rejected", ...DECIDED })),
    );
    const client = testQueryClient();
    client.setQueryData(invoiceQuery(ID).queryKey, storedInvoice());
    client.setQueryData(repairsQuery(ID).queryKey, [listedRepair()]);
    renderIn(
      "sr-Latn",
      <RepairView invoiceId={ID} repairId={REPAIR} />,
      client,
    );

    await decision();
    await press("Odbij");

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Popravka je odbijena, a faktura je ostala kakva je bila.",
    );
    expect(decisions(asked)).toEqual([`${PATH}/rejection`]);
    expect(screen.getByText("Odbijena")).toBeInTheDocument();
    const stale = (key: readonly unknown[]) =>
      client.getQueryState(key)?.isInvalidated;
    expect(stale(invoiceQuery(ID).queryKey)).toBe(false);
    expect(stale(repairsQuery(ID).queryKey)).toBe(true);
  });

  it("says what is under way while it is decided", async () => {
    keepSession();
    api(() => new Promise<Response>(() => {}));
    const { unmount } = renderIn(
      "sr-Latn",
      <RepairView invoiceId={ID} repairId={REPAIR} />,
    );

    await decision();
    await press("Odobri");
    await press("Da, odobri");

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Izmene se ponovo primenjuju i proveravaju…",
    );
    expect(
      screen.queryByRole("button", { name: "Odbij" }),
    ).not.toBeInTheDocument();
    unmount();

    renderIn("sr-Latn", <RepairView invoiceId={ID} repairId={REPAIR} />);
    await decision();
    await press("Odbij");

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Popravka se odbija…",
    );
  });

  it("offers no approval of a repair that changes nothing, only its rejection", async () => {
    keepSession();
    api(() => json(500, {}), repair({ changed: false, diff: "" }));
    renderIn("en", <RepairView invoiceId={ID} repairId={REPAIR} />);

    const heading = await screen.findByRole("heading", {
      level: 2,
      name: "Decision",
    });
    const section = within(heading.closest("section") as HTMLElement);
    expect(
      section.getByText(/^These changes do not change the invoice/),
    ).toBeInTheDocument();
    expect(
      section.queryByRole("button", { name: "Approve" }),
    ).not.toBeInTheDocument();
    expect(section.getByRole("button", { name: "Reject" })).toBeInTheDocument();
  });

  it("says when the copy the approval would keep is not valid yet", async () => {
    keepSession();
    api(() => json(500, {}), repair({ valid: false }));
    renderIn("sr-Latn", <RepairView invoiceId={ID} repairId={REPAIR} />);

    expect(
      (await decision()).getByText(
        "Kopija posle ovih izmena još nije ispravna.",
      ),
    ).toBeInTheDocument();
  });

  it("is not asked of a repair decided already", async () => {
    keepSession();
    api(() => json(500, {}), repair({ status: "superseded", ...DECIDED }));
    renderIn("sr-Latn", <RepairView invoiceId={ID} repairId={REPAIR} />);

    await screen.findByRole("heading", { level: 1 });
    await aMoment();
    expect(
      screen.queryByRole("heading", { level: 2, name: "Odluka" }),
    ).not.toBeInTheDocument();
  });

  it.each([
    [
      json(409, {
        detail: "the repair changes nothing",
        reason: "changes-nothing",
      }),
      "Ove izmene ne menjaju fakturu, pa nema šta da se odobri.",
      false,
    ],
    [
      json(409, { detail: "the invoice changed", reason: "invoice-changed" }),
      "Faktura se promenila otkad je popravka predložena. Zatražite novu popravku.",
      false,
    ],
    [
      json(409, {
        detail: "the patches leave another",
        reason: "outcome-changed",
      }),
      "Izmene više ne daju dokument koji su davale kad su predložene. Zatražite novu popravku.",
      false,
    ],
    [
      json(403, { detail: "a person decides on a repair" }),
      "O popravci odlučuje osoba prijavljena svojim nalogom.",
      true,
    ],
    [
      json(404, { detail: "no such repair of this invoice" }),
      "Ova popravka ne postoji, ili faktura nije vaša.",
      true,
    ],
    [
      json(429, { detail: "too many" }, { "Retry-After": "7" }),
      "Previše zahteva. Pokušajte ponovo za 7 s.",
      true,
    ],
    [
      json(503, { detail: "the validator is busy" }, { "Retry-After": "3" }),
      "Validator je zauzet. Pokušajte ponovo za 3 s.",
      true,
    ],
    [
      json(503, { detail: "the validator is not available" }),
      "Validator trenutno ne radi. Pokušajte ponovo malo kasnije.",
      true,
    ],
    [
      json(507, { detail: "the organization stores as much as it may" }),
      "Organizacija već čuva onoliko faktura koliko sme. Obrišite neku, pa pokušajte ponovo.",
      true,
    ],
    [
      json(422, { detail: "could not be validated within the time limit" }),
      "Odluka nije zabeležena. Pokušajte ponovo malo kasnije.",
      true,
    ],
  ])(
    "says why an approval was refused (%#), and offers it again only where it could pass",
    async (answer, said, approvable) => {
      keepSession();
      const asked = api(() => answer.clone());
      renderIn("sr-Latn", <RepairView invoiceId={ID} repairId={REPAIR} />);

      await decision();
      await press("Odobri");
      await press("Da, odobri");

      const section = await decision();
      expect(await section.findByRole("alert")).toHaveTextContent(said);
      expect(section.queryByRole("button", { name: "Odobri" }) !== null).toBe(
        approvable,
      );
      expect(
        section.getByRole("button", { name: "Odbij" }),
      ).toBeInTheDocument();
      // The page knows the outcome, so the repair is not read again.
      await aMoment();
      expect(reads(asked)).toBe(1);
    },
  );

  it.each([
    [
      () => json(409, { detail: "the repair is rejected", reason: "decided" }),
      "O ovoj popravci je već odlučeno.",
    ],
    [
      () =>
        Promise.reject(
          new DOMException("no answer in 60000 ms", "TimeoutError"),
        ),
      "Odgovor nije stigao na vreme. Stanje popravke je ponovo učitano iznad: proverite ga pre nego što pokušate ponovo.",
    ],
    [
      () => Promise.reject(new TypeError("Failed to fetch")),
      "API ne odgovara. Stanje popravke se ponovo učitava: proverite ga pre nego što pokušate ponovo.",
    ],
    [
      () => json(504, { detail: "gateway timeout" }),
      "API nije jasno odgovorio. Stanje popravke je ponovo učitano: proverite ga pre nego što pokušate ponovo.",
    ],
  ])(
    "reads the repair again when its outcome is not known here (%#), and shows where it stands",
    async (answer, said) => {
      keepSession();
      const asked = api(
        answer,
        repair(),
        repair({
          status: "rejected",
          decided_by: "u-bob",
          decided_at: DECIDED.decided_at,
        }),
      );
      renderIn("sr-Latn", <RepairView invoiceId={ID} repairId={REPAIR} />);

      await decision();
      await press("Odobri");
      await press("Da, odobri");

      await waitFor(() => expect(reads(asked)).toBe(2));
      expect(await screen.findByText("Odbijena")).toBeInTheDocument();
      const section = await decision();
      expect(section.getByRole("alert")).toHaveTextContent(said);
      // Decided meanwhile: nothing is left to decide.
      expect(section.queryByRole("button")).not.toBeInTheDocument();
    },
  );
});
