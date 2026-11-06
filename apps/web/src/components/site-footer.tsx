import { useTranslations } from "next-intl";

/** The bottom of every page: what the project is, and what it is not. */
export function SiteFooter() {
  const t = useTranslations("footer");
  return (
    <footer className="border-t">
      <div className="mx-auto w-full max-w-5xl px-6 py-6 text-sm text-balance text-muted-foreground">
        <p>{t("notice")}</p>
      </div>
    </footer>
  );
}
