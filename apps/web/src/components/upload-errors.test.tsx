import { renderHook } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";
import { SignedOutError } from "@/lib/session";
import { MESSAGES } from "@/test/render";

import { useUploadErrorMessage } from "./upload-errors";

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
  const { result } = renderHook(() => useUploadErrorMessage(), { wrapper });
  return result.current(error);
}

describe("Why an invoice was not kept", () => {
  it("is said for each answer of the API", () => {
    const cases: [ApiError, string][] = [
      [new SignedOutError(), "Sesija je istekla. Prijavite se ponovo."],
      [new ApiError(403, "forbidden"), "Nemate dozvolu da šaljete fakture."],
      [
        new ApiError(408, "slow"),
        "Faktura nije primljena na vreme. Pokušajte ponovo.",
      ],
      [
        new ApiError(413, "large"),
        "Faktura je prevelika: ima više bajtova ili elemenata nego što ovaj server prima.",
      ],
      [new ApiError(415, "not xml"), "Pošaljite fakturu kao XML (UBL 2.1)."],
      [
        new ApiError(422, "rules"),
        "Validator nije stigao da proveri fakturu na vreme, ili na nju nije mogao da primeni pravila.",
      ],
      [
        new ApiError(429, "many", { retryAfter: 7 }),
        "Previše provera. Pokušajte ponovo za 7 s.",
      ],
      [
        new ApiError(503, "busy", { retryAfter: 1 }),
        "Validator je zauzet. Pokušajte ponovo za 1 s.",
      ],
      [
        new ApiError(503, "no validator"),
        "Validator trenutno nije dostupan. Pokušajte ponovo malo kasnije.",
      ],
      [
        new ApiError(507, "full"),
        "Organizacija je popunila prostor za fakture. Obrišite neke, pa pokušajte ponovo.",
      ],
      [new ApiError(500, "error"), "Faktura nije sačuvana. Pokušajte ponovo."],
    ];
    for (const [error, message] of cases) {
      expect(messageFor(error)).toBe(message);
    }
  });

  it("is that the API is not answering, when the browser could not ask it", () => {
    expect(messageFor(new TypeError("Failed to fetch"))).toBe(
      "API ne odgovara. Pokušajte ponovo malo kasnije.",
    );
  });
});
