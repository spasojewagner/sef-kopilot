import { useTranslations } from "next-intl";

import { Account } from "@/components/account";
import { LanguageSwitcher } from "@/components/language-switcher";
import { Link } from "@/i18n/navigation";

/** The top of every page: the way to the home page, the interface's languages, the account. */
export function SiteHeader() {
  const t = useTranslations("header");
  return (
    <header className="border-b">
      <div className="mx-auto flex h-14 w-full max-w-5xl items-center justify-between gap-4 px-6">
        <Link href="/" className="font-semibold tracking-tight">
          {t("home")}
        </Link>
        <div className="flex items-center gap-2">
          <LanguageSwitcher />
          <Account />
        </div>
      </div>
    </header>
  );
}
