"use client";

import { CircleAlert, CircleCheck, CircleDashed } from "lucide-react";
import { useTranslations } from "next-intl";

import { RuleExplanation } from "@/components/invoice-explanations";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { Explanation } from "@/lib/explanations";
import type { Report } from "@/lib/invoices";
import type { RuleViolations } from "@/lib/report";
import { cn } from "@/lib/utils";

/**
 * One rule the invoice fails, what its source says, and every place it fails it; and the
 * explanation of it, once the visitor has asked for one.
 */
export function RuleCard({
  rule,
  explanation,
}: {
  rule: RuleViolations;
  explanation?: Explanation;
}) {
  const t = useTranslations("report");
  return (
    <Card className="gap-4 py-5">
      <CardHeader className="px-5">
        <CardTitle className="flex flex-wrap items-center gap-2">
          <h3 className="font-mono text-base">{rule.ruleId}</h3>
          <Badge variant={rule.severity === "fatal" ? "error" : "warning"}>
            {t(`severity.${rule.severity}`)}
          </Badge>
          <Badge variant="outline">{t(`layers.${rule.layer}`)}</Badge>
        </CardTitle>
        <CardDescription lang="en" className="text-foreground">
          {rule.message}
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-2 px-5">
        <p className="text-sm text-muted-foreground">
          {t("places", { count: rule.violations.length })}
        </p>
        <ul className="grid gap-1 text-sm">
          {rule.violations.map((violation, index) => (
            <li key={index} className="flex flex-wrap gap-x-3">
              <code className="font-mono text-xs break-all">
                {violation.xpath ?? t("wholeDocument")}
              </code>
              {typeof violation.line === "number" && (
                <span className="text-muted-foreground">
                  {t("line", { line: violation.line })}
                </span>
              )}
            </li>
          ))}
        </ul>
        {explanation && <RuleExplanation explanation={explanation} />}
      </CardContent>
    </Card>
  );
}

/**
 * What each layer of the validator did, in the order it ran them, as a checklist: a layer that
 * found nothing, one that found something, one that did not run. The words say what the marks
 * do, which are hidden from screen readers.
 */
export function ReportLayers({ report }: { report: Report }) {
  const t = useTranslations("report");
  return (
    <section
      className="grid gap-4 rounded-xl border bg-card p-5 text-card-foreground shadow-sm"
      aria-labelledby="layers"
    >
      <h2 id="layers" className="text-base font-semibold tracking-tight">
        {t("layersTitle")}
      </h2>
      <ol className="relative grid gap-4">
        <span
          aria-hidden="true"
          className="absolute top-2 bottom-2 left-[9px] w-px bg-border"
        />
        {report.layers.map((layer) => (
          <li
            key={layer.layer}
            className="relative grid grid-cols-[1.25rem_minmax(0,1fr)] gap-3 text-sm"
          >
            <LayerMark ran={layer.ran} found={layer.violations} />
            <div className="grid gap-0.5">
              <span className="font-medium">{t(`layers.${layer.layer}`)}</span>
              <span className="text-muted-foreground">
                {layer.ran
                  ? t("layerFound", { count: layer.violations })
                  : t("layerSkipped")}
              </span>
              {layer.note && (
                <span lang="en" className="text-xs text-muted-foreground">
                  {layer.note}
                </span>
              )}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

/** A layer's mark: a check, an alert, or an empty ring for a layer that did not run. */
function LayerMark({ ran, found }: { ran: boolean; found: number }) {
  const Mark = !ran ? CircleDashed : found > 0 ? CircleAlert : CircleCheck;
  return (
    <Mark
      aria-hidden="true"
      className={cn(
        "relative mt-px size-5 rounded-full bg-card",
        !ran
          ? "text-muted-foreground"
          : found > 0
            ? "text-destructive"
            : "text-success",
      )}
    />
  );
}
