import { useTranslations } from "next-intl";

import { Link } from "@/i18n/navigation";

/** A path of the interface that names no page, in the visitor's language. */
export default function NotFound() {
  const t = useTranslations("notFound");
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-4 px-6 py-24 text-center">
      <h1 className="text-2xl font-semibold">{t("title")}</h1>
      <Link className="underline underline-offset-4" href="/">
        {t("home")}
      </Link>
    </main>
  );
}
