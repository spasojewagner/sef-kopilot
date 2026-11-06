"use client";

import { useLocale, useTranslations } from "next-intl";
import { Suspense } from "react";

import { buttonVariants } from "@/components/ui/button";
import { Link, usePathname } from "@/i18n/navigation";
import { routing, type Locale } from "@/i18n/routing";
import { cn } from "@/lib/utils";

/** Each language by its own name, so that a visitor finds theirs whatever the page's. */
const NAMES: Record<Locale, string> = { "sr-Latn": "Srpski", en: "English" };

const LINK = buttonVariants({ variant: "ghost", size: "sm" });

/**
 * The languages where a page places them. A page whose path is known only when it is asked
 * for renders the links then, and React shows them a moment after the rest; until then their
 * place is kept, so that nothing beside them moves when they come.
 */
export function Languages({ className }: { className?: string }) {
  return (
    <div className={className}>
      <Suspense fallback={<LanguagesToCome />}>
        <LanguageSwitcher />
      </Suspense>
    </div>
  );
}

/** The same page in each of the interface's languages. */
export function LanguageSwitcher() {
  const t = useTranslations("header");
  const current = useLocale();
  const pathname = usePathname();
  return (
    <nav aria-label={t("language")}>
      <ul className="flex gap-1">
        {routing.locales.map((locale) => (
          <li key={locale}>
            <Link
              href={pathname}
              locale={locale}
              lang={locale}
              hrefLang={locale}
              aria-current={locale === current ? "true" : undefined}
              className={cn(
                LINK,
                "text-muted-foreground aria-[current]:text-foreground",
              )}
            >
              {NAMES[locale]}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}

/** The links' place: the same names in the same boxes, neither seen nor read. */
function LanguagesToCome() {
  return (
    <ul aria-hidden="true" className="invisible flex gap-1">
      {routing.locales.map((locale) => (
        <li key={locale}>
          <span className={LINK}>{NAMES[locale]}</span>
        </li>
      ))}
    </ul>
  );
}
