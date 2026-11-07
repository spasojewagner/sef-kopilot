import path from "node:path";

import { expect, test } from "@playwright/test";

/**
 * The golden path, in a browser: a person registers, uploads an invoice the validator finds
 * invalid, reads its report, has the language model suggest a repair, approves it, and finds
 * the invoice valid. Every request goes to the API as it runs, with its database, its validator
 * and its repairer; only the model's answer is scripted (`scripts/serve_e2e_api.py`).
 */

/** An invoice whose type code, 393, is not one SEF accepts (SRB-001). */
const INVOICE = path.join(
  __dirname,
  "../../../fixtures/invoices/synthetic/mutations/srb-001-invoice-type-code.xml",
);
const NUMBER = "RF-2026-000123";
const UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";

test("an invalid invoice, repaired by the model and approved by a person, is valid", async ({
  page,
}) => {
  // What the pages log as an error, a failed render or a refused request among them.
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") {
      errors.push(message.text());
    }
  });
  page.on("pageerror", (error) => errors.push(error.message));

  await test.step("no page lets another site show it in a frame", async () => {
    const response = await page.goto("/sr-Latn/register");

    expect(response?.headers()["content-security-policy"]).toBe(
      "frame-ancestors 'none'",
    );
    expect(response?.headers()["x-frame-options"]).toBe("DENY");
  });

  await test.step("the pages wear the brand, and a key leads past the header", async () => {
    await page.goto("/sr-Latn/register");

    // The typeface is the one the pages load, not a fallback of the system's.
    await page.evaluate(() => document.fonts.ready);
    const loaded = await page.evaluate(() =>
      [...document.fonts]
        .filter((face) => face.status === "loaded")
        .map((face) => face.family.replaceAll('"', "")),
    );
    expect(loaded).toContain("Onest Variable");
    expect(
      await page.evaluate(() => getComputedStyle(document.body).fontFamily),
    ).toMatch(/^"?Onest Variable/);
    const icon = await page.request.get(
      (await page
        .locator('link[rel="icon"][type="image/svg+xml"]')
        .getAttribute("href"))!,
    );
    expect(icon.headers()["content-type"]).toContain("image/svg+xml");
    // A shared link's image, at the address the site is served at.
    const shared = await page
      .locator('meta[property="og:image"]')
      .getAttribute("content");
    expect(shared).toMatch(/^http:\/\/localhost:3100\/.*opengraph-image/);
    const image = await page.request.get(shared!);
    expect(image.headers()["content-type"]).toBe("image/png");

    await page.keyboard.press("Tab");
    const skip = page.getByRole("link", { name: "Pređi na sadržaj" });
    await expect(skip).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("main")).toBeFocused();
  });

  await test.step("the home page's example shows its end to a visitor who asks for less motion", async () => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/sr-Latn");

    const opacity = (selector: string) =>
      page.locator(selector).evaluate((node) => getComputedStyle(node).opacity);
    expect(await opacity(".story-valid")).toBe("1");
    expect(await opacity(".story-invalid")).toBe("0");
    expect(await opacity(".story-patch")).toBe("1");
    await page.emulateMedia({ reducedMotion: null });
  });

  await test.step("a person registers, with an organization of their own", async () => {
    const email = `marija.${Date.now()}@primer.example`;
    await page.goto("/sr-Latn/register");
    await page.getByLabel("Adresa e-pošte").fill(email);
    await page
      .getByLabel("Lozinka")
      .fill("a long passphrase for the smoke test");
    await page.getByLabel("Naziv organizacije").fill("Primer d.o.o.");
    await page.getByRole("button", { name: "Napravi nalog" }).click();

    await expect(page).toHaveURL("/sr-Latn");
    await expect(page.getByRole("banner")).toContainText(email);
  });

  await test.step("uploads an invoice, which the validator finds invalid", async () => {
    await page.getByRole("link", { name: "Proverite fakturu" }).click();
    await page.getByLabel("Faktura (UBL 2.1 XML)").setInputFiles(INVOICE);
    await page.getByRole("button", { name: "Proveri i sačuvaj" }).click();

    await expect(page).toHaveURL(new RegExp(`/sr-Latn/invoices/${UUID}$`));
    const report = page.getByRole("article");
    await expect(report.getByRole("heading", { level: 1 })).toHaveText(NUMBER);
    await expect(
      report.locator("header").getByText("Neispravna", { exact: true }),
    ).toBeVisible();
  });

  await test.step("reads its report, and again after a reload", async () => {
    const report = page.getByRole("article");
    const rule = report.getByRole("heading", { level: 3, name: "SRB-001" });
    await expect(
      report.getByRole("heading", {
        level: 2,
        name: "1 greška, nema upozorenja",
      }),
    ).toBeVisible();
    await expect(rule).toBeVisible();

    // The tab keeps the session, and the page of any invoice reads its id from the address.
    await page.reload();

    await expect(rule).toBeVisible();
    await expect(page.getByRole("banner")).toContainText("@primer.example");
  });

  await test.step("finds it invalid in the list, and opens it again", async () => {
    await page.getByRole("link", { name: "Nazad na fakture" }).click();

    await expect(page).toHaveURL("/sr-Latn/invoices");
    const listed = page.getByRole("row", { name: new RegExp(NUMBER) });
    await expect(
      listed.getByRole("cell", { name: "Neispravna", exact: true }),
    ).toBeVisible();
    await listed.getByRole("link", { name: NUMBER }).click();

    await expect(page).toHaveURL(new RegExp(`/sr-Latn/invoices/${UUID}$`));
  });

  await test.step("asks the language model for a repair, and reads it", async () => {
    await page.getByRole("button", { name: "Predloži popravku" }).click();

    await expect(page).toHaveURL(
      new RegExp(`/sr-Latn/invoices/${UUID}/repairs/${UUID}$`),
    );
    const repair = page.getByRole("article");
    await expect(
      repair.locator("header").getByText("Čeka odluku", { exact: true }),
    ).toBeVisible();
    const diff = repair.getByRole("group", { name: "Razlika u fakturi" });
    await expect(diff.getByRole("deletion")).toContainText(
      "<cbc:InvoiceTypeCode>393</cbc:InvoiceTypeCode>",
    );
    await expect(diff.getByRole("insertion")).toContainText(
      "<cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>",
    );
    await expect(
      repair.getByRole("heading", { level: 2, name: "Izveštaj posle izmena" }),
    ).toBeVisible();
  });

  await test.step("approves it, with a second press", async () => {
    const repair = page.getByRole("article");
    await repair.getByRole("button", { name: "Odobri", exact: true }).click();
    await repair.getByRole("button", { name: "Da, odobri" }).click();

    await expect(repair.getByRole("status")).toHaveText(
      "Popravka je odobrena: faktura je sada kopija sa ovim izmenama.",
    );
    await expect(
      repair.locator("header").getByText("Odobrena", { exact: true }),
    ).toBeVisible();
  });

  await test.step("finds the invoice valid, on its report and in the list", async () => {
    await page.getByRole("link", { name: "Nazad na izveštaj" }).click();

    await expect(page).toHaveURL(new RegExp(`/sr-Latn/invoices/${UUID}$`));
    const report = page.getByRole("article");
    await expect(
      report.locator("header").getByText("Ispravna", { exact: true }),
    ).toBeVisible();
    await expect(
      report.getByRole("heading", {
        level: 2,
        name: "Nema grešaka, nema upozorenja",
      }),
    ).toBeVisible();
    await expect(report.getByRole("row", { name: /Odobrena/ })).toBeVisible();

    await page.getByRole("link", { name: "Nazad na fakture" }).click();

    await expect(page).toHaveURL("/sr-Latn/invoices");
    const listed = page.getByRole("row", { name: new RegExp(NUMBER) });
    await expect(
      listed.getByRole("cell", { name: "Ispravna", exact: true }),
    ).toBeVisible();
  });

  expect(errors).toEqual([]);
});
