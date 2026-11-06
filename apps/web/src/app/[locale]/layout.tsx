import type { Metadata } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getTranslations } from "next-intl/server";

import { LanguageSwitcher } from "@/components/language-switcher";
import { routing } from "@/i18n/routing";

import "../globals.css";

/** Every page is rendered once for each language, when the application is built. */
export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("metadata");
  return { title: t("title"), description: t("description") };
}

export default async function LocaleLayout({
  children,
}: LayoutProps<"/[locale]">) {
  const locale = await getLocale();
  const t = await getTranslations("footer");
  return (
    <html lang={locale} className="h-full antialiased">
      <body className="flex min-h-full flex-col">
        <NextIntlClientProvider>
          <header className="flex justify-end px-6 py-4">
            <LanguageSwitcher />
          </header>
          {children}
          <footer className="px-6 py-6 text-center text-sm text-balance text-zinc-500 dark:text-zinc-400">
            {t("notice")}
          </footer>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
