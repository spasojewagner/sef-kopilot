import { CircleAlert, CircleCheck } from "lucide-react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";

/** The example's XML around the line the validator finds wrong, which alone fits a phone. */
const BEFORE = "<cbc:IssueDate>2026-10-05</cbc:IssueDate>";
const AFTER = "<cbc:DocumentCurrencyCode>RSD</cbc:DocumentCurrencyCode>";

/**
 * The home page's example of what the application does, as one invoice's report: the error the
 * validator finds, the model's explanation and its citation, the repair a person approved, and
 * the verdict once the invoice is checked again. It plays once as the page opens; a visitor who
 * asks for less motion sees its end at once. It is drawn as the page would draw it, not on the
 * navy around it, and a screen reader reads its caption instead.
 */
export function ReportPreview({ className }: { className?: string }) {
  const t = useTranslations("home.preview");
  const verdict = useTranslations("verdict");
  return (
    <figure
      aria-labelledby="home-example"
      className={cn("surface-page", className)}
    >
      <figcaption id="home-example" className="sr-only">
        {t("caption")}
      </figcaption>
      <div
        aria-hidden="true"
        className="overflow-hidden rounded-2xl border bg-card text-sm text-card-foreground shadow-[0_24px_60px_-20px_oklch(0.17_0.05_251/0.55)]"
      >
        <div className="flex items-center justify-between gap-4 border-b px-5 py-4">
          <div className="grid gap-0.5">
            <p className="font-semibold tracking-tight tabular-nums">
              RF-2026-000123
            </p>
            <p className="text-xs text-muted-foreground">{t("profile")}</p>
          </div>
          <div className="grid justify-items-end">
            <span
              className={cn(
                "story-invalid",
                "col-start-1 row-start-1 inline-flex items-center gap-1 rounded-md bg-destructive/10 px-2 py-1 text-xs font-medium text-destructive",
              )}
            >
              <CircleAlert className="size-3.5" />
              {verdict("invalid")}
            </span>
            <span
              className={cn(
                "story-valid",
                "col-start-1 row-start-1 inline-flex items-center gap-1 rounded-md bg-success/10 px-2 py-1 text-xs font-medium text-success",
              )}
            >
              <CircleCheck className="size-3.5" />
              {verdict("valid")}
            </span>
          </div>
        </div>

        <pre className="overflow-x-auto border-b bg-muted/50 py-3 font-mono text-[0.75rem] leading-6">
          <span className="block px-5 text-muted-foreground max-sm:hidden">
            {BEFORE}
          </span>
          <span className="story-line block px-5">
            <span className="text-muted-foreground">
              {"<cbc:InvoiceTypeCode>"}
            </span>
            <del className="story-old">393</del>
            <ins className="story-new">380</ins>
            <span className="text-muted-foreground">
              {"</cbc:InvoiceTypeCode>"}
            </span>
          </span>
          <span className="block px-5 text-muted-foreground max-sm:hidden">
            {AFTER}
          </span>
        </pre>

        <div className="grid gap-4 px-5 py-4">
          <div className="grid gap-1.5">
            <p className="flex items-center gap-2">
              <span className="font-mono text-[0.8125rem] font-semibold">
                SRB-001
              </span>
              <span className="rounded-md bg-destructive/10 px-1.5 py-0.5 text-xs font-medium text-destructive">
                {t("error")}
              </span>
            </p>
            <p className="text-muted-foreground">{t("rule")}</p>
          </div>

          <div
            className={cn(
              "story-explanation",
              "grid gap-1.5 border-l-2 border-brand pl-3",
            )}
          >
            <p>{t("explanation")}</p>
            <p className="text-xs text-muted-foreground">{t("citation")}</p>
          </div>

          <div
            className={cn(
              "story-patch",
              "flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border px-3 py-2",
            )}
          >
            <span className="font-mono text-xs text-muted-foreground">
              {t("replace")} cbc:InvoiceTypeCode
            </span>
            <span className="font-mono text-xs font-semibold tabular-nums">
              393 → 380
            </span>
            <span className="ml-auto text-xs font-medium text-success">
              {t("approved")}
            </span>
          </div>

          <p
            className={cn(
              "story-checked",
              "flex items-center gap-2 text-xs font-medium text-success",
            )}
          >
            <CircleCheck className="size-4" />
            {t("after")}
          </p>
        </div>
      </div>
    </figure>
  );
}
