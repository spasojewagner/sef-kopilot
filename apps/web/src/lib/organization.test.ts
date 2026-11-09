import { describe, expect, it } from "vitest";

import {
  deletesInvoices,
  isModelKey,
  isModelName,
  isSefKey,
  storedBefore,
} from "./organization";

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

describe("A key to SEF", () => {
  it.each([
    ["4711-4711", true],
    ["  4711-4711-4711-4711 ", true],
    ["a".repeat(200), true],
    ["4711-47", false],
    ["a".repeat(201), false],
    ["4711 4711 4711", false],
    ["ključ-4711-4711", false],
    ["4711\t4711\t4711", false],
    ["", false],
  ])("%j may be one: %s", (written, may) => {
    expect(isSefKey(written)).toBe(may);
  });
});

describe("A key to a model", () => {
  it.each([
    ["own_4711-4711", true],
    ["  own-model-key-4711 ", true],
    ["a".repeat(300), true],
    ["4711-47", false],
    ["a".repeat(301), false],
    ["a key with spaces", false],
    ["ključ-4711-4711", false],
  ])("%j may be one: %s", (written, may) => {
    expect(isModelKey(written)).toBe(may);
  });
});

describe("A model's name", () => {
  it.each([
    ["claude-haiku-5-5", true],
    ["openai/gpt-oss-120b", true],
    [" gpt-6-luna ", true],
    ["llama3.3:70b", true],
    ["m".repeat(200), true],
    ["m".repeat(201), false],
    ["-dash-first", false],
    ["gpt 6", false],
    ["", false],
  ])("%j may be one: %s", (written, may) => {
    expect(isModelName(written)).toBe(may);
  });
});
