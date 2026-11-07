import type { Metadata } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getTranslations } from "next-intl/server";

import { ApiWakingNotice } from "@/components/api-waking-notice";
import { QueryProvider } from "@/components/query-provider";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import { routing } from "@/i18n/routing";
import { siteUrl } from "@/lib/links";

// The typefaces are served with the pages, from the packages' files (ADR-0043): Onest for the
// text, JetBrains Mono for rule ids, paths and XML. Each file covers a range of characters, so
// a browser loads Latin, Latin Extended (č, ć, đ, š, ž) or Cyrillic only when a page has them.
import "@fontsource-variable/onest";
import "@fontsource-variable/jetbrains-mono";
import "../globals.css";

/** Every page is rendered once for each language, when the application is built. */
export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("metadata");
  return {
    metadataBase: siteUrl(),
    // A page that names itself is "Prijava · SEF Kopilot".
    title: { default: t("title"), template: `%s · ${t("title")}` },
    description: t("description"),
    // A shared link shows `opengraph-image.png`, large.
    twitter: { card: "summary_large_image" },
  };
}

export default async function LocaleLayout({
  children,
}: LayoutProps<"/[locale]">) {
  const locale = await getLocale();
  return (
    <html lang={locale} className="h-full antialiased">
      <body className="flex min-h-full flex-col">
        <NextIntlClientProvider>
          <QueryProvider>
            <SiteHeader />
            <ApiWakingNotice />
            {/* The one main landmark of every page, where the header's first link leads. */}
            <main
              id="main"
              tabIndex={-1}
              className="flex flex-1 flex-col outline-none"
            >
              {children}
            </main>
            <SiteFooter />
          </QueryProvider>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
