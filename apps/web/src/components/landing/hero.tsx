import { ArrowUpRight } from "lucide-react";
import Image from "next/image";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Link } from "@/i18n/navigation";
import { REPOSITORY_URL } from "@/lib/links";

import backdrop from "./backdrop.svg";
import { ReportPreview } from "./report-preview";

/**
 * The home page's first screen, on the brand's navy: what the product does and the way to try
 * it, beside an example of a report. Behind them, a chart: contour lines, a compass bezel open
 * at its diagonals as the mark is, and a route that leaves it through the north-east gap. On a
 * wide screen the example reaches past the navy's edge, into room the section keeps below it.
 */
/** A name that stays whole on one line, rather than breaking after "e-" or "SRB-". */
function whole(name: ReactNode) {
  return <span className="whitespace-nowrap">{name}</span>;
}

export function Hero() {
  const t = useTranslations("home");
  return (
    <section
      aria-labelledby="home-title"
      className="relative isolate z-10 surface-ink"
    >
      {/* The navy, and the chart on it, stop short of the example's foot on a wide screen. */}
      <div className="absolute inset-x-0 top-0 bottom-0 -z-10 bg-background lg:bottom-28">
        <Image
          src={backdrop}
          alt=""
          fill
          unoptimized
          className="object-cover"
        />
      </div>
      <div className="page-width grid grid-cols-[minmax(0,1fr)] items-center gap-12 pt-14 pb-16 sm:pt-20 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] lg:gap-14 lg:pt-24 lg:pb-28">
        <div className="lg:pb-24">
          <h1
            id="home-title"
            className="text-[2.5rem] leading-[1.08] font-semibold tracking-[-0.03em] sm:text-5xl lg:text-[3.5rem]"
          >
            {t.rich("title", { whole })}
          </h1>
          <p className="mt-6 max-w-[36rem] text-lg leading-relaxed text-muted-foreground">
            {t.rich("tagline", { whole })}
          </p>
          <div className="mt-9 flex flex-wrap gap-3">
            <Button
              asChild
              size="lg"
              className="bg-brand text-brand-foreground hover:bg-brand/90"
            >
              <Link href="/invoices">{t("check")}</Link>
            </Button>
            <Button asChild size="lg" variant="outline">
              <a
                href={REPOSITORY_URL}
                target="_blank"
                rel="noopener noreferrer"
              >
                {t("source")}
                <ArrowUpRight aria-hidden="true" />
              </a>
            </Button>
          </div>
          <p className="mt-6 text-sm text-muted-foreground">
            {t("small", { status: t("status") })}
          </p>
        </div>
        <ReportPreview className="lg:-mb-28 lg:self-end" />
      </div>
    </section>
  );
}
