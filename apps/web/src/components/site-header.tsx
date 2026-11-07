import { useTranslations } from "next-intl";

import { Account } from "@/components/account";
import { Languages } from "@/components/language-switcher";
import { Logo } from "@/components/logo";
import { Sections } from "@/components/sections";
import { Link } from "@/i18n/navigation";

/**
 * The top of every page, on the brand's navy: the way to the home page, the sections of a
 * member who is signed in, the interface's languages and the account. It keeps to one line at
 * every width down to 320 px: a phone's sections are icons and its languages are in the
 * footer, and the product's name gives way to the mark beside a member's sections. A keyboard
 * reaches the page's content first, by a link that shows itself when it has the focus.
 */
export function SiteHeader() {
  const t = useTranslations("header");
  return (
    <header className="group/header sticky top-0 z-40 border-b surface-ink">
      <a
        href="#main"
        className="sr-only rounded-md bg-brand px-3 py-2 text-sm font-medium text-brand-foreground focus:not-sr-only focus:absolute focus:top-3 focus:left-4 focus:z-50"
      >
        {t("skip")}
      </a>
      <div className="page-width flex h-16 items-center gap-2 sm:gap-6">
        <Link
          href="/"
          className="shrink-0 rounded-md outline-none focus-visible:ring-[3px] focus-visible:ring-ring/60"
        >
          <Logo
            name={t("home")}
            nameClassName="max-sm:group-has-[[data-sections]]/header:sr-only"
          />
        </Link>
        <Sections />
        <div className="ml-auto flex min-w-0 items-center gap-2">
          {/* A phone's header has room for the account alone: its languages are in the footer. */}
          <Languages className="hidden sm:block" />
          <Account />
        </div>
      </div>
    </header>
  );
}
