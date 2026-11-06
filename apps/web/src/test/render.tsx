import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
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

/** A cache of the API's answers for one test, which tries a failed request only once. */
export function testQueryClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

/**
 * ``ui`` rendered as the application renders it in ``locale``: with that language's messages,
 * and with a cache of the API's answers of its own.
 */
export function renderIn(
  locale: Locale,
  ui: ReactElement,
  client: QueryClient = testQueryClient(),
): RenderResult {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={MESSAGES[locale]}
      timeZone="Europe/Belgrade"
    >
      <QueryClientProvider client={client}>{ui}</QueryClientProvider>
    </NextIntlClientProvider>,
  );
}
