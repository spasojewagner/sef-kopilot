import { describe, expect, it } from "vitest";

import { json, keepSession, stubApi } from "@/test/api";
import { READ } from "@/test/extraction";

import {
  documentTypeOf,
  draftFileName,
  draftInvoice,
  emptyLine,
  fieldsOf,
  formOf,
  missingIn,
  readInvoice,
  READING_TIMEOUT_MS,
} from "./extraction";

describe("What a chosen document is read as", () => {
  it.each([
    ["racun.pdf", "application/pdf", "application/pdf"],
    ["racun.jpg", "image/jpeg", "image/jpeg"],
    ["racun.png", "image/png", "image/png"],
    ["racun.webp", "image/webp", "image/webp"],
    // A browser that gives no media type: the name says.
    ["RACUN.PDF", "", "application/pdf"],
    ["slika.JPEG", "", "image/jpeg"],
    ["slika.png", "", "image/png"],
    // Pictures the API does not read.
    ["slika.heic", "image/heic", null],
    ["slika.gif", "image/gif", null],
    ["faktura.xml", "text/xml", null],
  ])("%s, given as %j, is %s", (name, type, read) => {
    expect(documentTypeOf(new File(["x"], name, { type }))).toBe(read);
  });
});

describe("The fields in the form", () => {
  it("hold every value as text, an empty one where nothing was read", () => {
    const form = formOf(READ);

    expect(form.delivery_date).toBe("");
    expect(form.buyer.tax_id).toBe("");
    expect(form.seller_in_vat_register).toBe("yes");
    expect(form.lines[0].vat_category).toBe("S");
    expect(form.totals.prepaid).toBe("");
  });

  it("go back to the API as they came, an empty value as none", () => {
    expect(fieldsOf(formOf(READ))).toEqual(READ);
  });

  it("read the seller's VAT register as unknown, yes or no", () => {
    expect(
      formOf({ seller_in_vat_register: null }).seller_in_vat_register,
    ).toBe("");
    expect(
      formOf({ seller_in_vat_register: false }).seller_in_vat_register,
    ).toBe("no");
    const form = formOf(READ);
    expect(
      fieldsOf({ ...form, seller_in_vat_register: "" }).seller_in_vat_register,
    ).toBeNull();
    expect(
      fieldsOf({ ...form, seller_in_vat_register: "no" })
        .seller_in_vat_register,
    ).toBe(false);
  });

  it("are empty, every one of them, where the API read nothing", () => {
    const form = formOf({});

    expect(form.lines).toEqual([]);
    expect(form.seller.name).toBe("");
    expect(fieldsOf(form)).toMatchObject({
      number: null,
      seller: { name: null, tax_id: null },
      lines: [],
      totals: { payable: null },
    });
  });

  it("trim what a person typed", () => {
    const form = formOf(READ);
    form.number = "  RF-2026-000200 ";
    form.lines = [{ ...emptyLine(), name: " Popravka ", quantity: "  " }];

    const fields = fieldsOf(form);

    expect(fields.number).toBe("RF-2026-000200");
    expect(fields.lines?.[0]).toMatchObject({
      name: "Popravka",
      quantity: null,
    });
  });
});

describe("What SEF needs and was not read", () => {
  it("is nothing for an invoice read whole", () => {
    expect(
      missingIn(
        formOf({ ...READ, buyer: { ...READ.buyer, tax_id: "100000016" } }),
      ),
    ).toEqual([]);
  });

  it("names each field, in the order of the form", () => {
    expect(missingIn(formOf(READ))).toEqual(["buyer.tax_id"]);
    expect(missingIn(formOf({}))).toEqual([
      "number",
      "issue_date",
      "currency",
      "seller.name",
      "seller.tax_id",
      "buyer.name",
      "buyer.tax_id",
      "lines",
      "totals.payable",
    ]);
  });
});

describe("The drafted invoice's file", () => {
  it.each([
    ["RF-2026-000123", "RF-2026-000123.xml"],
    ["RF 2026/123", "RF-2026-123.xml"],
    ["Račun 7", "Račun-7.xml"],
    ["", "faktura.xml"],
  ])("for number %j is %s", (number, name) => {
    expect(draftFileName({ ...formOf(READ), number })).toBe(name);
  });
});

describe("The API's reading", () => {
  it("is sent the document as it is, and given the time a model needs", async () => {
    keepSession();
    const asked = stubApi(() =>
      json(200, {
        fields: READ,
        document: { kind: "picture", pages: 1, text: false },
        model: "groq/qwen/qwen3.8-27b",
      }),
    );
    const picture = new Blob([new Uint8Array([0xff, 0xd8, 0xff])]);

    const read = await readInvoice(picture, "image/jpeg");

    expect(read.model).toBe("groq/qwen/qwen3.8-27b");
    expect(asked[0]).toMatchObject({
      method: "POST",
      path: "/invoices/extract",
    });
    expect(asked[0].headers.get("Content-Type")).toBe("image/jpeg");
    expect(asked[0].body).toBe(picture);
    expect(READING_TIMEOUT_MS).toBeGreaterThanOrEqual(120_000);
  });

  it("drafts the invoice of the fields, as XML", async () => {
    keepSession();
    const asked = stubApi(
      () =>
        new Response("<Invoice/>", {
          status: 200,
          headers: { "Content-Type": "application/xml" },
        }),
    );

    await expect(draftInvoice(READ)).resolves.toBe("<Invoice/>");

    expect(asked[0]).toMatchObject({ method: "POST", path: "/invoices/draft" });
    expect(asked[0].headers.get("Content-Type")).toBe("application/json");
    expect(asked[0].headers.get("Accept")).toBe("application/xml");
    expect(JSON.parse(String(asked[0].body))).toEqual(READ);
  });
});
