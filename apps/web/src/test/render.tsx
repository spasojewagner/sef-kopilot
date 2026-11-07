import { type QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderResult } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactElement } from "react";
import { renderToString } from "react-dom/server";

import { makeQueryClient } from "@/components/query-provider";
import type { Locale } from "@/i18n/routing";
import en from "../../messages/en.json";
import srLatn from "../../messages/sr-Latn.json";

export const MESSAGES: Record<Locale, typeof srLatn> = {
  "sr-Latn": srLatn,
  en,
};

/**
 * A cache of the API's answers for one test, with the pages' defaults: an answer the test puts
 * in it stays fresh, as it would on a page. A failed request is not tried again, which would
 * only slow the test down.
 */
export function testQueryClient(): QueryClient {
  const client = makeQueryClient();
  const { queries } = client.getDefaultOptions();
  client.setDefaultOptions({ queries: { ...queries, retry: false } });
  return client;
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

/**
 * ``ui`` as the server sends it in ``locale``, before any script of the page has run: its
 * markup, in an element of its own that no page holds.
 */
export function asSentIn(locale: Locale, ui: ReactElement): HTMLElement {
  const html = renderToString(
    <NextIntlClientProvider
      locale={locale}
      messages={MESSAGES[locale]}
      timeZone="Europe/Belgrade"
    >
      <QueryClientProvider client={testQueryClient()}>{ui}</QueryClientProvider>
    </NextIntlClientProvider>,
  );
  const sent = document.createElement("div");
  sent.innerHTML = html;
  return sent;
}
