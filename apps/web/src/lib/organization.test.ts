import { describe, expect, it } from "vitest";

import { deletesInvoices, storedBefore } from "./organization";

describe("A change of the period", () => {
  it.each([
    [null, 30, true],
    [365, 30, true],
    [365, 364, true],
    [30, 365, false],
    [30, 30, false],
    [365, null, false],
    [null, null, false],
  ])("from %s to %s days deletes invoices: %s", (before, after, deletes) => {
    expect(deletesInvoices(before, after)).toBe(deletes);
  });

  it("deletes the invoices stored that many days before now, or earlier", () => {
    expect(storedBefore(90, new Date("2026-11-07T12:00:00Z"))).toEqual(
      new Date("2026-08-09T12:00:00Z"),
    );
  });
});
