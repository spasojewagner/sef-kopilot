import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { explanationsQuery, invoiceQuery } from "@/lib/queries";
import { aMoment, type Asked, json, keepSession, stubApi } from "@/test/api";
import { explained, storedInvoice } from "@/test/invoices";
import { renderIn, testQueryClient } from "@/test/render";

import { InvoiceReport } from "./invoice-report";

const ID = "0b3f6a2e-1c4d-4e5f-8a9b-0c1d2e3f4a5b";

/** An API that has the stored invoice, and answers a request for its explanations so. */
function api(explanations: (asked: Asked) => Response | Promise<Response>) {
  return stubApi((asked) =>
    asked.path.endsWith("/explanations")
      ? explanations(asked)
      : json(200, storedInvoice()),
  );
}

/** The card of the rule ``ruleId``. */
function card(ruleId: string) {
  const heading = screen.getByRole("heading", { level: 3, name: ruleId });
  return within(heading.closest("[data-slot=card]") as HTMLElement);
}

async function ask(name = "Objasni pravila") {
  await userEvent.setup().click(await screen.findByRole("button", { name }));
}

describe("The explanations on an invoice's report", () => {
  it("are written when the visitor asks, and not before", async () => {
    keepSession();
    const asked = api(() => json(200, explained()));
    renderIn("sr-Latn", <InvoiceReport id={ID} />);

    expect(
      await screen.findByText(/koja može navesti vrednost iz fakture/),
    ).toBeInTheDocument();
    expect(asked.map((request) => request.path)).toEqual([`/invoices/${ID}`]);

    await ask();

    expect(
      await screen.findByText(
        "PIB prodavca mora imati devet cifara i ispravnu kontrolnu cifru.",
      ),
    ).toBeInTheDocument();
    expect(
      card("SRB-009").getByText("Šta promeniti:").closest("p"),
    ).toHaveTextContent(
      "Šta promeniti: Upišite PIB prodavca iz rešenja o registraciji.",
    );
    expect(
      card("BR-CO-15").getByText(
        "Ukupan iznos sa PDV-om je zbir iznosa bez PDV-a i PDV-a.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Prema propisima na dan 5. 11. 2026. objašnjenja je napisao jezički model test/quoting. Svaki citat je odlomak propisa koji je model dobio.",
      ),
    ).toBeInTheDocument();
    expect(
      asked.map(({ method, path, search }) => `${method} ${path}${search}`),
    ).toEqual([
      `GET /invoices/${ID}`,
      `POST /invoices/${ID}/explanations?language=sr`,
    ]);
  });

  it("cite each passage with a link to its source, its edition and when it applies", async () => {
    keepSession();
    api(() => json(200, explained()));
    renderIn("sr-Latn", <InvoiceReport id={ID} />);

    await ask();

    const rule = card("SRB-009");
    const link = await rule.findByRole("link", { name: /^Члан 2\./ });
    expect(link).toHaveAttribute(
      "href",
      "https://pravno-informacioni-sistem.rs/eli/rep/sgrs/ministarstva/pravilnik/2003/57/1/reg",
    );
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer");
    expect(link).toHaveTextContent(
      "Члан 2. Поступак, начин и рокови одређивања и додељивања ПИБ-а — Pravilnik o poreskom identifikacionom broju",
    );
    expect(within(link).getByText("Члан 2.")).toHaveAttribute(
      "lang",
      "sr-Cyrl",
    );
    expect(
      within(link).getByText(
        "Поступак, начин и рокови одређивања и додељивања ПИБ-а",
      ),
    ).toHaveAttribute("lang", "sr-Cyrl");
    expect(
      rule.getByText(
        "Službeni glasnik RS, br. 57/2003, 68/2003, 32/2009, 48/2010 i 44/2018, važi od 1. 10. 2018.",
      ),
    ).toBeInTheDocument();
    expect(rule.getByText("BT-31")).not.toHaveAttribute("lang");
  });

  it("say when a cited passage stops applying, and link only to a secure source", async () => {
    keepSession();
    const written = explained();
    const [citation] = written.explanations[0].citations;
    written.explanations[0].citations = [
      {
        ...citation,
        valid_to: "2026-12-31",
        source_url: "http://pravno-informacioni-sistem.rs/",
      },
    ];
    api(() => json(200, written));
    renderIn("sr-Latn", <InvoiceReport id={ID} />);

    await ask();

    const rule = card("SRB-009");
    expect(
      await rule.findByText(/važi od 1\. 10\. 2018\. do 31\. 12\. 2026\.$/),
    ).toBeInTheDocument();
    expect(rule.queryByRole("link")).not.toBeInTheDocument();
    expect(rule.getByText(/^Члан 2\./)).toBeInTheDocument();
  });

  it("are written in English on an English page", async () => {
    keepSession();
    const asked = api(() => json(200, explained({ language: "en" })));
    renderIn("en", <InvoiceReport id={ID} />);

    await ask("Explain the rules");

    expect(
      await screen.findByText(
        "Explained by the language model test/quoting, from the regulations as of Nov 5, 2026. Every citation is a passage the model was given.",
      ),
    ).toBeInTheDocument();
    expect(asked[1].search).toBe("?language=en");
  });

  it("name the rules left for later, and a rule the model could not explain", async () => {
    keepSession();
    const written = explained({ unexplained: ["BR-CO-16"] });
    written.explanations[0] = {
      ...written.explanations[0],
      text: null,
      fix: null,
      citations: [],
      problem: "the model's answer cited a passage it was not given",
    };
    api(() => json(200, written));
    renderIn("sr-Latn", <InvoiceReport id={ID} />);

    await ask();

    expect(
      await screen.findByText(
        "Ovaj put nisu objašnjena: BR-CO-16. Objasniće se kad se isprave pravila iznad.",
      ),
    ).toBeInTheDocument();
    expect(
      card("SRB-009").getByText(
        "Ovo pravilo ovaj put nije objašnjeno. Pokušajte ponovo.",
      ),
    ).toBeInTheDocument();
    expect(
      card("SRB-009").queryByText(/model's answer/),
    ).not.toBeInTheDocument();
  });

  it("say when no model is set up, which asking again would not change", async () => {
    keepSession();
    api(() =>
      json(503, { detail: "no language model is configured on this server" }),
    );
    renderIn("sr-Latn", <InvoiceReport id={ID} />);

    await ask();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Na ovom serveru nije podešen jezički model, pa objašnjenja nisu dostupna.",
    );
    expect(
      screen.queryByRole("button", { name: "Pokušaj ponovo" }),
    ).not.toBeInTheDocument();
  });

  it("say so while the model writes them", async () => {
    keepSession();
    let answer: (response: Response) => void = () => undefined;
    api(
      () =>
        new Promise<Response>((resolve) => {
          answer = resolve;
        }),
    );
    renderIn("sr-Latn", <InvoiceReport id={ID} />);

    await ask();

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Jezički model piše objašnjenja. Može potrajati do pola minuta…",
    );
    answer(json(200, explained()));
    expect(
      await screen.findByText(
        "PIB prodavca mora imati devet cifara i ispravnu kontrolnu cifru.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("say how long to wait when the model has had too many requests", async () => {
    keepSession();
    api(() =>
      json(
        429,
        {
          detail: "too many requests to the language model; try again in 30 s",
        },
        { "Retry-After": "30" },
      ),
    );
    renderIn("sr-Latn", <InvoiceReport id={ID} />);

    await ask();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Previše zahteva jezičkom modelu. Pokušajte ponovo za 30 s.",
    );
  });

  it("say when they did not arrive in time or the API did not answer, and try again", async () => {
    keepSession();
    const answers = [
      () =>
        Promise.reject(
          new DOMException("no answer in 60000 ms", "TimeoutError"),
        ),
      () => Promise.reject(new TypeError("Failed to fetch")),
      () => json(200, explained()),
    ];
    const asked = api(() => (answers.shift() ?? (() => json(500, {})))());
    renderIn("sr-Latn", <InvoiceReport id={ID} />);

    await ask();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Objašnjenja nisu stigla na vreme. Pokušajte ponovo.",
    );

    await ask("Pokušaj ponovo");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "API ne odgovara. Pokušajte ponovo malo kasnije.",
    );

    await ask("Pokušaj ponovo");

    expect(
      await screen.findByText(
        "PIB prodavca mora imati devet cifara i ispravnu kontrolnu cifru.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(asked.map((request) => request.method)).toEqual([
      "GET",
      "POST",
      "POST",
      "POST",
    ]);
  });

  it("written in another language are not shown, but offered in the page's", async () => {
    keepSession();
    const asked = stubApi(() => json(500, { detail: "not asked" }));
    const client = testQueryClient();
    client.setQueryData(invoiceQuery(ID).queryKey, storedInvoice());
    client.setQueryData(explanationsQuery(ID, "sr").queryKey, explained());

    renderIn("en", <InvoiceReport id={ID} />, client);
    await aMoment();

    expect(
      screen.getByRole("button", { name: "Explain the rules" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(
        "PIB prodavca mora imati devet cifara i ispravnu kontrolnu cifru.",
      ),
    ).not.toBeInTheDocument();
    expect(asked).toEqual([]);
  });

  it("are not offered for an invoice without violations", async () => {
    keepSession();
    const valid = storedInvoice();
    valid.report = { ...valid.report, valid: true, violations: [] };
    stubApi(() => json(200, valid));
    renderIn("sr-Latn", <InvoiceReport id={ID} />);

    expect(
      await screen.findByText("Validator nije našao nijedan prekršaj."),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Objasni pravila" }),
    ).not.toBeInTheDocument();
  });

  it("written earlier in the visit are shown at once, without asking the model again", async () => {
    keepSession();
    const asked = stubApi(() => json(500, { detail: "not asked" }));
    const client = testQueryClient();
    client.setQueryData(invoiceQuery(ID).queryKey, storedInvoice());
    client.setQueryData(explanationsQuery(ID, "sr").queryKey, explained());

    renderIn("sr-Latn", <InvoiceReport id={ID} />, client);
    await aMoment();

    expect(
      screen.getByText(
        "PIB prodavca mora imati devet cifara i ispravnu kontrolnu cifru.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Objasni pravila" }),
    ).not.toBeInTheDocument();
    expect(asked).toEqual([]);
  });
});
