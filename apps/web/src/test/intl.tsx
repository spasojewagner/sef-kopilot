import { render, type RenderResult } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactElement } from "react";

import type { Locale } from "@/i18n/routing";
import en from "../../messages/en.json";
import srLatn from "../../messages/sr-Latn.json";

export const MESSAGES: Record<Locale, typeof srLatn> = {
  "sr-Latn": srLatn,
  en,
};

/** ``ui`` rendered as the application renders it in ``locale``, with that language's messages. */
export function renderIn(locale: Locale, ui: ReactElement): RenderResult {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={MESSAGES[locale]}
      timeZone="Europe/Belgrade"
    >
      {ui}
    </NextIntlClientProvider>,
  );
}
