"use client";

import { useLocale, useTranslations } from "next-intl";
import { Suspense, useSyncExternalStore } from "react";

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

function onHistory(change: () => void): () => void {
  window.addEventListener("popstate", change);
  return () => window.removeEventListener("popstate", change);
}

/**
 * The query of the page's address, `?request=…`, which a page built ahead of time does not
 * know: read in the browser once the page is there, and again whenever it renders.
 */
function useAddressQuery(): string {
  return useSyncExternalStore(
    onHistory,
    () => window.location.search,
    () => "",
  );
}

/**
 * The same page in each of the interface's languages, with the query of its address: a page
 * that reads it, such as the one where a person decides on an MCP client's request, is still
 * itself in the other language.
 */
export function LanguageSwitcher() {
  const t = useTranslations("header");
  const current = useLocale();
  const pathname = usePathname();
  const query = useAddressQuery();
  return (
    <nav aria-label={t("language")}>
      <ul className="flex gap-1">
        {routing.locales.map((locale) => (
          <li key={locale}>
            <Link
              href={`${pathname}${query}`}
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
