import { useTranslations } from "next-intl";

import { ApiStatus } from "@/components/api-status";
import { Languages } from "@/components/language-switcher";

/**
 * The bottom of every page: what the project is and is not, and whether the API answers; and on
 * a phone, whose header has no room for them, the interface's languages.
 */
export function SiteFooter() {
  const t = useTranslations("footer");
  return (
    <footer className="border-t">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-3 px-6 py-6 text-sm text-muted-foreground sm:flex-row sm:justify-between sm:gap-8">
        <Languages className="-ml-3 sm:hidden" />
        <p className="text-balance">{t("notice")}</p>
        <ApiStatus />
      </div>
    </footer>
  );
}
