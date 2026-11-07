import Image from "next/image";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import backdrop from "@/components/landing/backdrop.svg";
import { LogoMark } from "@/components/logo";

/**
 * The page around signing in and registering: the form, and on a wide screen, beside it, the
 * brand's navy with the home page's chart and what the product holds to. A phone shows the form
 * alone.
 */
export function AuthFrame({ children }: { children: ReactNode }) {
  const t = useTranslations("home.route");
  return (
    <div className="grid flex-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <div className="flex flex-col justify-center px-4 py-12 sm:px-6 lg:py-20">
        <div className="mx-auto w-full max-w-sm">{children}</div>
      </div>
      <aside className="relative isolate hidden overflow-hidden bg-background surface-ink lg:flex lg:flex-col lg:justify-end">
        <Image
          src={backdrop}
          alt=""
          fill
          unoptimized
          className="-z-10 object-cover object-left"
        />
        <div className="grid max-w-lg gap-5 p-12 xl:p-16">
          <LogoMark className="size-11" />
          <p className="text-2xl leading-snug font-semibold tracking-[-0.02em] text-balance">
            {t("title")}
          </p>
          <p className="leading-relaxed text-muted-foreground">{t("intro")}</p>
        </div>
      </aside>
    </div>
  );
}
