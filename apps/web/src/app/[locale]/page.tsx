import { ArrowUpRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Link } from "@/i18n/navigation";

const REPOSITORY_URL = "https://github.com/spasojewagner/sef-kopilot";

export default function HomePage() {
  const t = useTranslations("home");
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col items-center justify-center gap-6 px-6 py-24 text-center">
      <Badge variant="outline" className="tracking-wide uppercase">
        {t("status")}
      </Badge>
      <h1 className="text-4xl font-semibold tracking-tight sm:text-5xl">
        {t("title")}
      </h1>
      <p className="max-w-xl text-lg text-balance text-muted-foreground">
        {t("tagline")}
      </p>
      <div className="flex flex-wrap justify-center gap-3">
        <Button asChild>
          <Link href="/invoices">{t("check")}</Link>
        </Button>
        <Button asChild variant="outline">
          <a href={REPOSITORY_URL} target="_blank" rel="noopener noreferrer">
            {t("source")}
            <ArrowUpRight />
          </a>
        </Button>
      </div>
    </main>
  );
}
