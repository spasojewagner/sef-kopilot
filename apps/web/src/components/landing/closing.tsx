import { ArrowUpRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Link } from "@/i18n/navigation";
import { SYNTHETIC_INVOICES_URL } from "@/lib/links";

/** The page's end: the invoices to try it on, which are made up, and the way to begin. */
export function Closing() {
  const t = useTranslations("home.closing");
  return (
    <section
      aria-labelledby="closing-title"
      className="page-width pb-20 lg:pb-28"
    >
      <div className="grid grid-cols-[minmax(0,1fr)] gap-8 rounded-3xl bg-background px-6 py-12 surface-ink sm:px-12 sm:py-14 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
        <div>
          <h2
            id="closing-title"
            className="text-3xl leading-tight font-semibold tracking-[-0.02em] sm:text-4xl"
          >
            {t("title")}
          </h2>
          <p className="mt-4 max-w-[38rem] leading-relaxed text-muted-foreground">
            {t("text")}
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Button
            asChild
            size="lg"
            className="bg-brand text-brand-foreground hover:bg-brand/90"
          >
            <Link href="/invoices">{t("start")}</Link>
          </Button>
          <Button asChild size="lg" variant="outline">
            <a
              href={SYNTHETIC_INVOICES_URL}
              target="_blank"
              rel="noopener noreferrer"
            >
              {t("examples")}
              <ArrowUpRight aria-hidden="true" />
            </a>
          </Button>
        </div>
      </div>
    </section>
  );
}
