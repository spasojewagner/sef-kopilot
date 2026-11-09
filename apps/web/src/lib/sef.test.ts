import type { Query } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";
import { submissionsQuery, WATCH_INTERVAL_MS } from "@/lib/queries";

import { isFinal, isWatched, reasonOf, type Submission } from "./sef";

const NOW = Date.parse("2026-11-09T12:00:00Z");

function submission(changes: Partial<Submission> = {}): Submission {
  return {
    id: "s-1",
    invoice_id: "i-1",
    state: "imported",
    sales_invoice_id: 4711,
    sef_invoice_id: 815,
    sef_status: "Sent",
    refusal: null,
    detail: null,
    attempts: 1,
    sent_at: "2026-11-09T11:00:00Z",
    answered_at: "2026-11-09T11:00:01Z",
    checked_at: null,
    ...changes,
  };
}

describe("Where an invoice stands in SEF", () => {
  it.each([
    ["Approved", true],
    ["Rejected", true],
    ["Cancelled", true],
    ["Storno", true],
    ["Deleted", true],
    ["Sent", false],
    ["Mistake", false],
    ["Paid", false],
    [null, false],
  ])("%s is final: %s", (status, final) => {
    expect(isFinal(status)).toBe(final);
  });

  it.each([
    [submission(), true],
    [submission({ sef_status: null }), true],
    [submission({ sef_status: "Approved" }), false],
    [submission({ sent_at: "2026-10-10T11:00:00Z" }), false],
    [submission({ state: "refused" }), false],
    [submission({ state: "unconfirmed" }), false],
    [undefined, false],
  ])("%# is still asked about: %s", (latest, watched) => {
    expect(isWatched(latest, NOW)).toBe(watched);
  });

  it("is read again every half a minute while the API asks SEF, and not after", () => {
    const interval = submissionsQuery("i-1").refetchInterval as (
      query: Pick<Query<Submission[]>, "state">,
    ) => number | false;
    const reading = (data: Submission[] | undefined) =>
      interval({ state: { data } } as Pick<Query<Submission[]>, "state">);

    expect(reading([submission({ sent_at: new Date().toISOString() })])).toBe(
      WATCH_INTERVAL_MS,
    );
    expect(reading([submission({ sef_status: "Rejected" })])).toBe(false);
    expect(reading([])).toBe(false);
    expect(reading(undefined)).toBe(false);
  });
});

describe("Why an invoice was not sent", () => {
  it("is the reason of a 409, and nothing else's", () => {
    expect(
      reasonOf(new ApiError(409, "imported", { body: { reason: "sent" } })),
    ).toBe("sent");
    expect(reasonOf(new ApiError(409, "conflict", { body: {} }))).toBeNull();
    expect(
      reasonOf(new ApiError(422, "no", { body: { reason: "sent" } })),
    ).toBeNull();
    expect(reasonOf(new Error("offline"))).toBeNull();
  });
});
