import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Link } from "@/i18n/navigation";

/** A path of the interface that names no page, in the visitor's language. */
export default function NotFound() {
  const t = useTranslations("notFound");
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col items-center justify-center gap-6 px-6 py-24 text-center">
      <h1 className="text-2xl font-semibold tracking-tight">{t("title")}</h1>
      <Button asChild variant="outline">
        <Link href="/">{t("home")}</Link>
      </Button>
    </div>
  );
}
