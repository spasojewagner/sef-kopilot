"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { useApiWaking } from "@/hooks/use-api-waking";
import { healthQuery } from "@/lib/queries";
import { cn } from "@/lib/utils";

/** The colour of the dot beside the words, which say the same. */
const DOT = {
  pending: "bg-amber-500 motion-safe:animate-pulse",
  success: "bg-emerald-500",
  error: "bg-destructive",
} as const;

/**
 * Whether the API answers, and which version it runs, or that it is waking up while the pages
 * wait for it. Asked when the page opens, and again when the visitor comes back to it a minute
 * or more later.
 */
export function ApiStatus() {
  const t = useTranslations("footer.api");
  const health = useQuery(healthQuery);
  const waking = useApiWaking();
  return (
    <p role="status" className="flex shrink-0 items-center gap-2">
      <span
        aria-hidden="true"
        className={cn("size-2 rounded-full", DOT[health.status])}
      />
      {health.status === "pending"
        ? waking
          ? t("waking")
          : t("checking")
        : health.status === "error"
          ? t("unavailable")
          : t("available", { version: health.data.version })}
    </p>
  );
}
