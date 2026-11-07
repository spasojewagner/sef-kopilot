"use client";

import { useTranslations } from "next-intl";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { useApiWaking } from "@/hooks/use-api-waking";

/**
 * Says, above every page, that the API is waking up while the page waits for it (ADR-0036), so
 * that the visitor waits too, rather than leaving or sending again. The region is always there,
 * empty and without height until then, so that a screen reader announces the notice.
 */
export function ApiWakingNotice() {
  const t = useTranslations("apiWaking");
  const waking = useApiWaking();
  return (
    <div role="status" className="mx-auto w-full max-w-5xl px-6">
      {waking ? (
        // The region announces it, politely: no alert of its own.
        <Alert role="none" className="mt-6">
          <AlertTitle>{t("title")}</AlertTitle>
          <AlertDescription>{t("description")}</AlertDescription>
        </Alert>
      ) : null}
    </div>
  );
}
