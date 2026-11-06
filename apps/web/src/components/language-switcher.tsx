"use client";

import { useLocale, useTranslations } from "next-intl";

import { Link, usePathname } from "@/i18n/navigation";
import { routing, type Locale } from "@/i18n/routing";

/** Each language by its own name, so that a visitor finds theirs whatever the page's. */
const NAMES: Record<Locale, string> = { "sr-Latn": "Srpski", en: "English" };

/** The same page in each of the interface's languages. */
export function LanguageSwitcher() {
  const t = useTranslations("header");
  const current = useLocale();
  const pathname = usePathname();
  return (
    <nav aria-label={t("language")}>
      <ul className="flex gap-3 text-sm">
        {routing.locales.map((locale) => (
          <li key={locale}>
            <Link
              href={pathname}
              locale={locale}
              lang={locale}
              hrefLang={locale}
              aria-current={locale === current ? "true" : undefined}
              className="underline-offset-4 hover:underline aria-[current]:font-semibold"
            >
              {NAMES[locale]}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
