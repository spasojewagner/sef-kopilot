import { renderHook } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";
import { MESSAGES } from "@/test/render";

import { useAuthErrorMessage } from "./auth-errors";

function messageFor(error: unknown, locale: "sr-Latn" | "en" = "sr-Latn") {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <NextIntlClientProvider
      locale={locale}
      messages={MESSAGES[locale]}
      timeZone="Europe/Belgrade"
    >
      {children}
    </NextIntlClientProvider>
  );
  const { result } = renderHook(() => useAuthErrorMessage(), { wrapper });
  return result.current(error);
}

describe("What went wrong with a sign-in or a registration", () => {
  it("is said for each answer of the API, in the visitor's language", () => {
    expect(messageFor(new ApiError(401, "invalid"))).toBe(
      "Adresa ili lozinka nije tačna.",
    );
    expect(messageFor(new ApiError(403, "not a member"))).toBe(
      "Niste član te organizacije.",
    );
    expect(messageFor(new ApiError(409, "exists already"))).toBe(
      "Za ovu adresu već postoji nalog.",
    );
    expect(messageFor(new ApiError(422, "Field required"))).toBe(
      "Proverite unete podatke.",
    );
    expect(messageFor(new ApiError(500, "Internal Server Error"))).toBe(
      "Nije uspelo. Pokušajte ponovo.",
    );
    expect(messageFor(new ApiError(401, "invalid"), "en")).toBe(
      "The address or the password is wrong.",
    );
  });

  it("says how long to wait, or a minute when the API does not say", () => {
    expect(messageFor(new ApiError(429, "too many", { retryAfter: 12 }))).toBe(
      "Previše pokušaja. Pokušajte ponovo za 12 s.",
    );
    expect(messageFor(new ApiError(429, "too many"))).toBe(
      "Previše pokušaja. Pokušajte ponovo za 60 s.",
    );
  });

  it("is that the API is not answering, when the browser could not ask it", () => {
    expect(messageFor(new TypeError("Failed to fetch"))).toBe(
      "API ne odgovara. Pokušajte ponovo malo kasnije.",
    );
    expect(
      messageFor(new DOMException("no answer in 10000 ms", "TimeoutError")),
    ).toBe("API ne odgovara. Pokušajte ponovo malo kasnije.");
  });
});
