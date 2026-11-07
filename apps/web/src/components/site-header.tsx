import { useTranslations } from "next-intl";

import { Account } from "@/components/account";
import { Languages } from "@/components/language-switcher";
import { Link } from "@/i18n/navigation";

/**
 * The top of every page: the way to the home page, the interface's languages, the account. It
 * keeps to one line at every width down to 320 px: the account's address gives way first, a
 * phone's languages are in the footer, and its gaps narrow.
 */
export function SiteHeader() {
  const t = useTranslations("header");
  return (
    <header className="border-b">
      <div className="mx-auto flex h-14 w-full max-w-5xl items-center justify-between gap-2 px-6 sm:gap-4">
        <Link
          href="/"
          className="shrink-0 font-semibold tracking-tight whitespace-nowrap"
        >
          {t("home")}
        </Link>
        <div className="flex min-w-0 items-center gap-2">
          {/* A phone's header has room for the account alone: its languages are in the footer. */}
          <Languages className="hidden sm:block" />
          <Account />
        </div>
      </div>
    </header>
  );
}
