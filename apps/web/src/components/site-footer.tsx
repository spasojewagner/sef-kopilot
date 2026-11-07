import { ArrowUpRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { ApiStatus } from "@/components/api-status";
import { Languages } from "@/components/language-switcher";
import { Logo } from "@/components/logo";
import { REPOSITORY_URL } from "@/lib/links";

/**
 * The bottom of every page: what the project is and is not, where its code is, and whether the
 * API answers; and on a phone, whose header has no room for them, the interface's languages.
 */
export function SiteFooter() {
  const t = useTranslations("footer");
  const header = useTranslations("header");
  return (
    <footer className="border-t bg-card/60">
      <div className="page-width grid gap-6 py-10 text-sm sm:grid-cols-[minmax(0,1fr)_auto] sm:gap-12">
        <div className="grid content-start gap-3">
          <Logo name={header("home")} className="text-base" />
          <p className="max-w-xl text-muted-foreground">{t("notice")}</p>
        </div>
        <div className="grid content-start gap-3 sm:justify-items-end">
          <ApiStatus />
          <a
            href={REPOSITORY_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex w-fit items-center gap-1 rounded-sm text-muted-foreground underline-offset-4 outline-none hover:text-foreground hover:underline focus-visible:ring-[3px] focus-visible:ring-ring/50"
          >
            {t("source")}
            <ArrowUpRight aria-hidden="true" className="size-3.5" />
          </a>
          <Languages className="-ml-3 sm:hidden" />
        </div>
      </div>
    </footer>
  );
}
