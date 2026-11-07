import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  formatAmount,
  formatDate,
  formatDay,
  formatMoment,
  formatTime,
} from "./format";

describe("Amounts", () => {
  it("keep every digit the API sends, in the invoice's currency", () => {
    // The currency stays on the amount's line: a no-break space between them.
    expect(formatAmount("sr-Latn", "12345678901234567.89", "RSD")).toBe(
      "12.345.678.901.234.567,89\u00a0RSD",
    );
    expect(formatAmount("en", "1234.5", "EUR")).toBe("€1,234.50");
  });

  it("keep their decimals, two at least, whatever the currency's usual ones", () => {
    expect(formatAmount("sr-Latn", "14400.00", "RSD")).toBe(
      "14.400,00\u00a0RSD",
    );
    expect(formatAmount("sr-Latn", "1234.567", "RSD")).toBe(
      "1.234,567\u00a0RSD",
    );
    expect(formatAmount("en", "100", "JPY")).toBe("¥100.00");
  });

  it("have two decimals when the invoice names no currency", () => {
    expect(formatAmount("sr-Latn", "1234.5", null)).toBe("1.234,50");
  });
});

describe("Days and moments", () => {
  // A visitor west of Greenwich, where midnight UTC is still the day before. In Belgrade or in
  // UTC, where the tests usually run, a day written in the visitor's zone looks right.
  beforeEach(() => {
    vi.stubEnv("TZ", "America/Los_Angeles");
  });

  it("write an invoice's day as that day, wherever the visitor is", () => {
    expect(formatDay("sr-Latn", "2026-11-06")).toBe("6. 11. 2026.");
    expect(formatDay("en", "2026-01-01")).toBe("Jan 1, 2026");
  });

  it("write a moment in Belgrade's time, wherever the visitor is", () => {
    expect(formatMoment("sr-Latn", "2026-11-06T23:30:00Z")).toBe(
      "7. 11. 2026. 00:30",
    );
  });

  it("write the time of a moment as it is in Belgrade, wherever the visitor is", () => {
    expect(formatTime("sr-Latn", "2026-11-07T21:32:00Z")).toBe("22:32");
    // Before "PM", a space or a narrow one, as the version of the locale data (CLDR) has it.
    expect(formatTime("en", "2026-11-07T21:32:00Z")).toMatch(/^10:32\sPM$/);
  });

  it("write the day of a moment as it is in Belgrade, wherever the visitor is", () => {
    const moment = new Date("2026-10-08T22:30:00Z");

    expect(formatDate("sr-Latn", moment)).toBe("9. 10. 2026.");
    expect(formatDate("en", moment)).toBe("Oct 9, 2026");
  });
});
