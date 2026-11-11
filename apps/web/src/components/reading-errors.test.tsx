import { renderHook } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";
import { SignedOutError } from "@/lib/session";
import { MESSAGES } from "@/test/render";

import { useReadingErrorMessage } from "./reading-errors";

function messageFor(error: unknown) {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <NextIntlClientProvider
      locale="sr-Latn"
      messages={MESSAGES["sr-Latn"]}
      timeZone="Europe/Belgrade"
    >
      {children}
    </NextIntlClientProvider>
  );
  const { result } = renderHook(() => useReadingErrorMessage(), { wrapper });
  return result.current(error);
}

describe("Why a document was not read", () => {
  it.each([
    [new SignedOutError(), "Sesija je istekla. Prijavite se ponovo."],
    [new ApiError(403, "forbidden"), "Nemate dozvolu da proveravate fakture."],
    [
      new ApiError(408, "slow"),
      "Dokument nije primljen na vreme. Pokušajte ponovo.",
    ],
    [
      new ApiError(413, "the PDF has 4 pages"),
      "Dokument je prevelik: najviše 10 MB i tri strane.",
    ],
    [
      new ApiError(415, "not a document"),
      "Pošaljite PDF, ili JPEG, PNG ili WebP sliku.",
    ],
    [
      new ApiError(422, "the PDF cannot be opened"),
      "Dokument nije mogao da se pročita: oštećen je, zaštićen lozinkom, ili model u njemu nije našao fakturu.",
    ],
    [
      new ApiError(429, "too many", { retryAfter: 12 }),
      "Previše čitanja. Pokušajte ponovo za 12 s.",
    ],
    [
      new ApiError(502, "no answer"),
      "Jezički model nije odgovorio. Pokušajte ponovo.",
    ],
    [
      new ApiError(503, "no model"),
      "Na ovom serveru nije podešen jezički model, pa se dokumenti ne čitaju.",
    ],
    [
      new ApiError(504, "slow model"),
      "Model nije stigao da pročita dokument. Pokušajte sa manjom slikom ili PDF-om.",
    ],
    [
      new ApiError(500, "unexpected"),
      "Dokument nije pročitan. Pokušajte ponovo.",
    ],
    [
      new TypeError("Failed to fetch"),
      "API ne odgovara. Pokušajte ponovo malo kasnije.",
    ],
  ])("%s is said as %j", (error, message) => {
    expect(messageFor(error)).toBe(message);
  });

  it("asks for a minute when the API names no wait", () => {
    expect(messageFor(new ApiError(429, "too many"))).toBe(
      "Previše čitanja. Pokušajte ponovo za 60 s.",
    );
  });
});
