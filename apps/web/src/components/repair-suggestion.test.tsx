import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { repairQuery, repairsQuery } from "@/lib/queries";
import { aMoment, json, keepSession, stubApi } from "@/test/api";
import { storedInvoice } from "@/test/invoices";
import { listedRepair, repair } from "@/test/repairs";
import { renderIn, testQueryClient } from "@/test/render";

import { RepairSuggestion } from "./repair-suggestion";

const router = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
  prefetch: vi.fn(),
  back: vi.fn(),
  forward: vi.fn(),
  refresh: vi.fn(),
}));

vi.mock("next/navigation", async (importOriginal) => ({
  ...(await importOriginal<typeof import("next/navigation")>()),
  useRouter: () => router,
  usePathname: () => "/sr-Latn/invoices",
}));

const ID = storedInvoice().id;
const REPAIR = repair().id;

async function ask(name = "Predloži popravku") {
  await userEvent.setup().click(screen.getByRole("button", { name }));
}

describe("A repair the language model suggests", () => {
  it("is asked for only when the visitor asks, after the page says what the model is sent", async () => {
    keepSession();
    const asked = stubApi(() => json(201, repair()));
    renderIn("sr-Latn", <RepairSuggestion invoiceId={ID} />);
    await aMoment();

    expect(
      screen.getByText(
        "Modelu se šalju prekršaji, čije poruke mogu navesti vrednosti iz fakture, i polja fakture oko njih; ništa drugo iz nje.",
      ),
    ).toBeInTheDocument();
    expect(asked).toEqual([]);
  });

  it("is asked for in the page's language, and opens the repair the model wrote", async () => {
    keepSession();
    router.push.mockClear();
    const asked = stubApi(() => json(201, repair()));
    const client = testQueryClient();
    client.setQueryData(repairsQuery(ID).queryKey, [listedRepair()]);
    renderIn("en", <RepairSuggestion invoiceId={ID} />, client);

    await ask("Suggest a repair");

    await waitFor(() =>
      expect(router.push).toHaveBeenCalledWith(
        `/en/invoices/${ID}/repairs/${REPAIR}`,
      ),
    );
    expect(
      asked.map(({ method, path, search }) => `${method} ${path}${search}`),
    ).toEqual([`POST /invoices/${ID}/repairs/suggestion?language=en`]);
    // Its page shows it without asking again, and the invoice's list asks for it.
    expect(client.getQueryData(repairQuery(ID, REPAIR).queryKey)).toEqual(
      repair(),
    );
    expect(client.getQueryState(repairsQuery(ID).queryKey)?.isInvalidated).toBe(
      true,
    );
    expect(
      screen.getByRole("link", { name: "View the repair" }),
    ).toHaveAttribute("href", `/en/invoices/${ID}/repairs/${REPAIR}`);
  });

  it("says that the model is at work while it works", async () => {
    keepSession();
    stubApi(() => new Promise<Response>(() => {}));
    renderIn("sr-Latn", <RepairSuggestion invoiceId={ID} />);

    await ask();

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Jezički model predlaže izmene, a validator ih proverava. Može potrajati do pola minuta…",
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it.each([
    [
      json(409, {
        detail: "the invoice is valid",
        reason: "nothing-to-repair",
      }),
      "Faktura nema grešaka, pa nema šta da se popravi.",
      false,
    ],
    [
      json(409, { detail: "10 repairs wait", reason: "too-many-waiting" }),
      "Previše popravki ove fakture čeka odluku. Odobrite ili odbijte neku od njih, pa tražite novu.",
      false,
    ],
    [
      json(409, { detail: "the invoice changed", reason: "invoice-changed" }),
      "Faktura se promenila dok je model radio. Pokušajte ponovo.",
      true,
    ],
    [
      json(404, { detail: "no such invoice in this organization" }),
      "Ova faktura više ne postoji.",
      false,
    ],
    [
      json(422, { detail: "the language model proposes no patch" }),
      "Model nije predložio nijednu izmenu koju popravka može da zadrži. Pokušajte ponovo, ili ispravite fakturu sami.",
      true,
    ],
    [
      json(429, { detail: "too many requests" }, { "Retry-After": "12" }),
      "Previše zahteva. Pokušajte ponovo za 12 s.",
      true,
    ],
    [
      json(502, { detail: "the language model gave no answer" }),
      "Jezički model nije dao upotrebljiv odgovor. Pokušajte ponovo.",
      true,
    ],
    [
      json(503, { detail: "the validator is busy" }, { "Retry-After": "5" }),
      "Validator je zauzet. Pokušajte ponovo za 5 s.",
      true,
    ],
    [
      json(503, { detail: "no language model is configured on this server" }),
      "Popravke na ovom serveru nisu dostupne: nije podešen jezički model, ili validator ne radi.",
      false,
    ],
    [
      json(504, { detail: "no repair within the time allowed" }),
      "Popravka nije stigla na vreme. Pokušajte ponovo.",
      true,
    ],
    [
      json(500, {}),
      "Popravka nije predložena. Pokušajte ponovo malo kasnije.",
      true,
    ],
  ])(
    "says why there is none (%#), and offers to ask again only where that could help",
    async (answer, said, again) => {
      keepSession();
      stubApi(() => answer.clone());
      renderIn("sr-Latn", <RepairSuggestion invoiceId={ID} />);

      await ask();

      expect(await screen.findByRole("alert")).toHaveTextContent(said);
      expect(
        screen.queryByRole("button", { name: "Pokušaj ponovo" }) !== null,
      ).toBe(again);
    },
  );

  it("says when it did not arrive in time or the API did not answer, and asks again", async () => {
    keepSession();
    router.push.mockClear();
    const answers = [
      () =>
        Promise.reject(
          new DOMException("no answer in 60000 ms", "TimeoutError"),
        ),
      () => Promise.reject(new TypeError("Failed to fetch")),
      () => json(201, repair()),
    ];
    const asked = stubApi(() => (answers.shift() ?? (() => json(500, {})))());
    renderIn("sr-Latn", <RepairSuggestion invoiceId={ID} />);

    await ask();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Popravka nije stigla na vreme. Pokušajte ponovo.",
    );

    await ask("Pokušaj ponovo");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "API ne odgovara. Pokušajte ponovo malo kasnije.",
    );

    await ask("Pokušaj ponovo");
    await waitFor(() =>
      expect(router.push).toHaveBeenCalledWith(
        `/sr-Latn/invoices/${ID}/repairs/${REPAIR}`,
      ),
    );
    expect(asked).toHaveLength(3);
  });
});
