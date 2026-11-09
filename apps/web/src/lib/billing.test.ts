import { describe, expect, it } from "vitest";

import { formatPrice, returnedFrom } from "./billing";

describe("A pack's price", () => {
  it.each([
    ["en", 1000, "eur", "€10.00"],
    ["sr-Latn", 4000, "eur", "40,00 €"],
    ["en", 99, "usd", "$0.99"],
  ])("in %s, %i cents of %s, is %s", (locale, price, currency, written) => {
    expect(formatPrice(locale, { credits: 100, price, currency })).toBe(
      written.replace(" ", " "),
    );
  });
});

describe("Coming back from Stripe", () => {
  it.each([
    ["?checkout=paid", "paid"],
    ["?checkout=cancelled", "cancelled"],
    ["?checkout=anything", null],
    ["?other=paid", null],
    ["", null],
  ])("%j says %s", (search, returned) => {
    expect(returnedFrom(search)).toBe(returned);
  });
});
