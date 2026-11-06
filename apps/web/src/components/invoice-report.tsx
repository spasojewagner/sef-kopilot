"use client";

import { useQuery } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";

import { Verdict } from "@/components/verdict";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Link } from "@/i18n/navigation";
import { ApiError } from "@/lib/api";
import { formatAmount, formatDay, formatMoment } from "@/lib/format";
import type { Report, StoredInvoice } from "@/lib/invoices";
import { invoiceQuery } from "@/lib/queries";
import { byRule, type RuleViolations } from "@/lib/report";

/** The validator's report on the stored invoice ``id``. */
export function InvoiceReport({ id }: { id: string }) {
  const t = useTranslations("report");
  const invoice = useQuery(invoiceQuery(id));

  if (invoice.isPending) {
    return <p className="text-sm text-muted-foreground">{t("loading")}</p>;
  }
  if (invoice.isError) {
    const missing =
      invoice.error instanceof ApiError &&
      (invoice.error.status === 404 || invoice.error.status === 422);
    return (
      <div className="grid gap-4">
        <Alert variant="destructive">
          <AlertDescription>
            {missing ? t("notFound") : t("notLoaded")}
          </AlertDescription>
        </Alert>
        <BackToTheList />
      </div>
    );
  }
  return <Loaded invoice={invoice.data} />;
}

function BackToTheList() {
  const t = useTranslations("report");
  return (
    <div>
      <Button asChild variant="outline">
        <Link href="/invoices">{t("back")}</Link>
      </Button>
    </div>
  );
}

function Loaded({ invoice }: { invoice: StoredInvoice }) {
  const t = useTranslations("report");
  const profiles = useTranslations("profiles");
  const locale = useLocale();
  const { summary, report } = invoice;
  const rules = byRule(report);
  const fatal = report.violations.filter((v) => v.severity === "fatal").length;
  const warnings = report.violations.length - fatal;
  return (
    <article className="grid gap-8">
      <header className="grid gap-4">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold tracking-tight">
            {summary?.number ?? t("unreadable")}
          </h1>
          <Verdict valid={report.valid} />
        </div>
        {summary && (
          <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-4">
            <Fact term={t("seller")} value={summary.seller ?? "—"} />
            <Fact term={t("buyer")} value={summary.buyer ?? "—"} />
            <Fact
              term={t("issued")}
              value={formatDay(locale, summary.issue_date)}
            />
            <Fact
              term={t("amount")}
              value={formatAmount(
                locale,
                summary.payable_amount,
                summary.currency,
              )}
            />
          </dl>
        )}
        <p className="text-sm text-muted-foreground">
          {t("checked", {
            profile: profiles(invoice.profile),
            when: formatMoment(locale, invoice.validated_at),
          })}
        </p>
      </header>

      <section className="grid gap-4" aria-labelledby="violations">
        <h2 id="violations" className="text-lg font-semibold tracking-tight">
          {t("violations", { fatal, warnings })}
        </h2>
        {rules.length === 0 && (
          <p className="text-sm text-muted-foreground">{t("none")}</p>
        )}
        {rules.map((rule) => (
          <Rule key={`${rule.severity} ${rule.ruleId}`} rule={rule} />
        ))}
        {report.omitted > 0 && (
          <p className="text-sm text-muted-foreground">
            {t("omitted", { count: report.omitted })}
          </p>
        )}
        {report.set_aside.length > 0 && (
          <p className="text-sm text-muted-foreground">
            {t("setAside", { count: report.set_aside.length })}
          </p>
        )}
      </section>

      <Layers report={report} />
      <BackToTheList />
    </article>
  );
}

function Fact({ term, value }: { term: string; value: string }) {
  return (
    <div className="grid gap-1">
      <dt className="text-muted-foreground">{term}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}

/** One rule the invoice fails, what its source says, and every place it fails it. */
function Rule({ rule }: { rule: RuleViolations }) {
  const t = useTranslations("report");
  return (
    <Card className="gap-4 py-5">
      <CardHeader className="px-5">
        <CardTitle className="flex flex-wrap items-center gap-2">
          <h3 className="font-mono text-base">{rule.ruleId}</h3>
          <Badge
            variant={rule.severity === "fatal" ? "destructive" : "outline"}
          >
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
      </CardContent>
    </Card>
  );
}

/** What each layer of the validator did, in the order it ran them. */
function Layers({ report }: { report: Report }) {
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
