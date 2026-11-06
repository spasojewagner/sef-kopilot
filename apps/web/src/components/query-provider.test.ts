import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";

import { makeQueryClient } from "./query-provider";

/** Whether a question that failed ``failures`` times with ``error`` is asked again. */
function askedAgain(failures: number, error: Error): boolean {
  const retry = makeQueryClient().getDefaultOptions().queries?.retry;
  if (typeof retry !== "function") {
    throw new Error("the retry policy is not a function");
  }
  return retry(failures, error);
}

describe("The pages' questions to the API", () => {
  it("are asked once more when the API could not be reached or failed", () => {
    expect(askedAgain(0, new TypeError("Failed to fetch"))).toBe(true);
    expect(askedAgain(0, new ApiError(503, "Service Unavailable"))).toBe(true);
  });

  it("are not asked a third time", () => {
    expect(askedAgain(1, new TypeError("Failed to fetch"))).toBe(false);
    expect(askedAgain(1, new ApiError(500, "Internal Server Error"))).toBe(
      false,
    );
  });

  it("are not asked again when the API refused them", () => {
    expect(askedAgain(0, new ApiError(404, "no such invoice"))).toBe(false);
    expect(askedAgain(0, new ApiError(422, "Field required"))).toBe(false);
  });

  it("keep their answers fresh for a minute", () => {
    expect(makeQueryClient().getDefaultOptions().queries?.staleTime).toBe(
      60_000,
    );
  });
});
