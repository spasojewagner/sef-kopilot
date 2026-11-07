"use client";

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

/** What each layer of the validator did, in the order it ran them. */
export function ReportLayers({ report }: { report: Report }) {
  const t = useTranslations("report");
  return (
    <section className="grid gap-3" aria-labelledby="layers">
      <h2 id="layers" className="text-lg font-semibold tracking-tight">
        {t("layersTitle")}
      </h2>
      <ul className="grid gap-2 text-sm">
        {report.layers.map((layer) => (
          <li
            key={layer.layer}
            className="flex flex-wrap items-baseline gap-x-3"
          >
            <span className="font-medium">{t(`layers.${layer.layer}`)}</span>
            <span className="text-muted-foreground">
              {layer.ran
                ? t("layerFound", { count: layer.violations })
                : t("layerSkipped")}
            </span>
            {layer.note && (
              <span lang="en" className="text-muted-foreground">
                {layer.note}
              </span>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
