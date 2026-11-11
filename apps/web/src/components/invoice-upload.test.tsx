import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SYNTHETIC_INVOICES_URL } from "@/lib/links";
import { healthQuery, invoiceQuery, invoicesQuery } from "@/lib/queries";
import { json, keepSession, stubApi } from "@/test/api";
import { extraction } from "@/test/extraction";
import { storedInvoice } from "@/test/invoices";
import { renderIn, testQueryClient } from "@/test/render";

import { InvoiceUpload } from "./invoice-upload";

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

const XML = '<?xml version="1.0"?><Invoice/>';
/** The first bytes of a PNG file: its signature. */
const PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

async function upload(profile?: string, content = XML) {
  const user = userEvent.setup();
  await user.upload(
    screen.getByLabelText("Faktura (XML, PDF ili slika)"),
    new File([content], "faktura.xml", { type: "text/xml" }),
  );
  if (profile) {
    await user.selectOptions(screen.getByLabelText("Profil"), profile);
  }
  await user.click(screen.getByRole("button", { name: "Proveri i sačuvaj" }));
}

describe("Invoice upload", () => {
  it("sends the invoice under the profile chosen, and shows its report", async () => {
    keepSession();
    router.push.mockClear();
    const stored = storedInvoice();
    const asked = stubApi(() => json(201, stored));
    const client = testQueryClient();
    client.setQueryData(invoicesQuery.queryKey, {
      pages: [{ invoices: [], next: null }],
      pageParams: [null],
    });
    renderIn("sr-Latn", <InvoiceUpload />, client);

    await upload("en16931");

    await waitFor(() => expect(router.push).toHaveBeenCalled());
    expect(router.push.mock.calls[0][0]).toBe(`/sr-Latn/invoices/${stored.id}`);
    expect(asked).toHaveLength(1);
    expect(asked[0]).toMatchObject({
      method: "POST",
      path: "/invoices",
      search: "?profile=en16931",
    });
    expect(asked[0].headers.get("Content-Type")).toBe("application/xml");
    expect(asked[0].headers.get("Authorization")).toBe("Bearer access-2");
    expect(await (asked[0].body as File).text()).toBe(XML);
    expect(client.getQueryData(invoiceQuery(stored.id).queryKey)).toEqual(
      stored,
    );
    expect(client.getQueryState(invoicesQuery.queryKey)?.isInvalidated).toBe(
      true,
    );
  });

  it("validates under the Serbian profile unless told otherwise", async () => {
    keepSession();
    const asked = stubApi(() => json(201, storedInvoice()));
    renderIn("sr-Latn", <InvoiceUpload />);

    await upload();

    await waitFor(() => expect(asked).toHaveLength(1));
    expect(asked[0].search).toBe("?profile=srb");
  });

  it("asks for a file before sending anything", async () => {
    keepSession();
    const asked = stubApi(() => json(201, storedInvoice()));
    renderIn("sr-Latn", <InvoiceUpload />);

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Proveri i sačuvaj" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Izaberite fakturu: XML, PDF ili sliku.",
    );
    expect(
      screen.getByLabelText("Faktura (XML, PDF ili slika)"),
    ).toHaveAttribute("aria-invalid", "true");
    expect(asked).toEqual([]);
  });

  it("takes an empty file for no file at all", async () => {
    keepSession();
    const asked = stubApi(() => json(201, storedInvoice()));
    renderIn("sr-Latn", <InvoiceUpload />);

    await upload(undefined, "");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Izaberite fakturu: XML, PDF ili sliku.",
    );
    expect(asked).toEqual([]);
  });

  it("reads a picture of an invoice, and shows its fields beside it", async () => {
    keepSession();
    const asked = stubApi(() => json(200, extraction()));
    const made = vi.fn(() => "blob:racun");
    const given = vi.fn();
    vi.stubGlobal(
      "URL",
      Object.assign(URL, { createObjectURL: made, revokeObjectURL: given }),
    );
    renderIn("sr-Latn", <InvoiceUpload />);
    const user = userEvent.setup({ applyAccept: false });
    const picture = new File([PNG], "racun.png", { type: "image/png" });

    await user.upload(
      screen.getByLabelText("Faktura (XML, PDF ili slika)"),
      picture,
    );
    await user.selectOptions(screen.getByLabelText("Profil"), "en16931");
    await user.click(screen.getByRole("button", { name: "Proveri i sačuvaj" }));

    expect(
      await screen.findByRole("heading", { name: "Pročitano sa slike" }),
    ).toBeInTheDocument();
    expect(asked).toHaveLength(1);
    expect(asked[0]).toMatchObject({
      method: "POST",
      path: "/invoices/extract",
    });
    expect(asked[0].headers.get("Content-Type")).toBe("image/png");
    expect(asked[0].body).toBe(picture);
    expect(made).toHaveBeenCalledWith(picture);
    expect(screen.getByRole("img")).toHaveAttribute("src", "blob:racun");

    await user.click(screen.getByRole("button", { name: "Odustani" }));

    expect(
      screen.getByLabelText("Faktura (XML, PDF ili slika)"),
    ).toBeInTheDocument();
    expect(given).toHaveBeenCalledWith("blob:racun");
  });

  it("says the model is reading while it reads, and reads one document at a time", async () => {
    keepSession();
    let answer: (response: Response) => void = () => undefined;
    stubApi(
      () =>
        new Promise<Response>((resolve) => {
          answer = resolve;
        }),
    );
    renderIn("en", <InvoiceUpload />);
    const user = userEvent.setup({ applyAccept: false });

    await user.upload(
      screen.getByLabelText("Invoice (XML, PDF or picture)"),
      new File(["%PDF-1.7"], "invoice.pdf", { type: "application/pdf" }),
    );
    await user.click(screen.getByRole("button", { name: "Check and keep" }));

    expect(
      await screen.findByRole("button", {
        name: "The model is reading the document…",
      }),
    ).toBeDisabled();
    answer(
      json(503, { detail: "no language model is configured on this server" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "No language model is set up on this server, so documents are not read.",
    );
  });

  it("refuses a picture in a format that is not read, and sends the XML chosen next", async () => {
    keepSession();
    const asked = stubApi(() => json(201, storedInvoice()));
    renderIn("sr-Latn", <InvoiceUpload />);
    const user = userEvent.setup({ applyAccept: false });
    const file = screen.getByLabelText("Faktura (XML, PDF ili slika)");
    const send = screen.getByRole("button", { name: "Proveri i sačuvaj" });

    await user.upload(
      file,
      new File([PNG], "racun.heic", { type: "image/heic" }),
    );
    await user.click(send);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Ovaj format slike se ne čita: izaberite JPEG, PNG, WebP sliku ili PDF.",
    );
    expect(file).toHaveAttribute("aria-invalid", "true");
    expect(asked).toEqual([]);

    await user.upload(
      file,
      new File([XML], "faktura.xml", { type: "text/xml" }),
    );

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(file).not.toHaveAttribute("aria-invalid");
    await user.click(send);
    await waitFor(() => expect(asked).toHaveLength(1));
    expect(asked[0].path).toBe("/invoices");
  });

  it("refuses a document larger than the API reads, before sending it", async () => {
    keepSession();
    const asked = stubApi(() => json(200, extraction()));
    renderIn("sr-Latn", <InvoiceUpload />);
    const user = userEvent.setup({ applyAccept: false });
    const large = new File([PNG], "racun.jpg", { type: "image/jpeg" });
    Object.defineProperty(large, "size", { value: 11 * 1024 * 1024 });

    await user.upload(
      screen.getByLabelText("Faktura (XML, PDF ili slika)"),
      large,
    );
    await user.click(screen.getByRole("button", { name: "Proveri i sačuvaj" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Dokument je veći od 10 MB: izaberite manju sliku ili PDF.",
    );
    expect(asked).toEqual([]);
  });

  it("sends one invoice at a time", async () => {
    keepSession();
    let answer: (response: Response) => void = () => undefined;
    const asked = stubApi(
      () =>
        new Promise<Response>((resolve) => {
          answer = resolve;
        }),
    );
    renderIn("sr-Latn", <InvoiceUpload />);

    await upload();
    await waitFor(() => expect(asked).toHaveLength(1));

    expect(screen.getByRole("button", { name: "Provera…" })).toBeDisabled();
    answer(json(201, storedInvoice()));
    expect(
      await screen.findByRole("button", { name: "Proveri i sačuvaj" }),
    ).toBeEnabled();
  });

  it("says why the invoice was not kept", async () => {
    keepSession();
    stubApi(() =>
      json(507, { detail: "the organization stores as much as it may" }),
    );
    renderIn("sr-Latn", <InvoiceUpload />);

    await upload();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Organizacija je popunila prostor za fakture.",
    );
  });
});

describe("Invoice upload on a public demo", () => {
  /** A cache in which the footer's question had the API's health for its answer. */
  function answered(publicDemo: boolean) {
    const client = testQueryClient();
    client.setQueryData(healthQuery.queryKey, {
      status: "ok",
      service: "sef-kopilot-api",
      version: "0.2.0",
      public_demo: publicDemo,
    });
    return client;
  }

  it("asks for a synthetic invoice, and links to the repository's", () => {
    renderIn("sr-Latn", <InvoiceUpload />, answered(true));

    const note = screen.getByRole("note");
    expect(note).toHaveTextContent("Javni demo: samo sintetičke fakture");
    expect(note).toHaveTextContent(
      "Ono što otpremite čuva se na ovom serveru; PDF ili slika koju date na čitanje šalje se cela dobavljaču jezičkog modela, a objašnjenja i popravke mu šalju poruke pravila i polja fakture. Ne otpremajte pravu fakturu: uzmite neku od sintetičkih, sa izmišljenim firmama i PIB-ovima.",
    );
    expect(
      screen.getByRole("link", { name: "neku od sintetičkih" }),
    ).toHaveAttribute("href", SYNTHETIC_INVOICES_URL);
  });

  it("says nothing of it on a server that is no public demo", () => {
    renderIn("en", <InvoiceUpload />, answered(false));

    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });

  it("says nothing of it, and asks nothing, before the footer has the answer", async () => {
    const asked = stubApi(() => json(200, {}));

    renderIn("en", <InvoiceUpload />);
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(screen.queryByRole("note")).not.toBeInTheDocument();
    expect(asked).toEqual([]);
  });
});
