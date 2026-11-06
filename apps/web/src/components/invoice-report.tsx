"use client";

import { useQuery } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";

import { Fact } from "@/components/fact";
import {
  ExplanationsPanel,
  useExplanations,
} from "@/components/invoice-explanations";
import { ReportLayers, RuleCard } from "@/components/report-rules";
import { Verdict } from "@/components/verdict";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Link } from "@/i18n/navigation";
import { ApiError } from "@/lib/api";
import { formatAmount, formatDay, formatMoment } from "@/lib/format";
import type { StoredInvoice } from "@/lib/invoices";
import { invoiceQuery } from "@/lib/queries";
import { byRule } from "@/lib/report";

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
  const explaining = useExplanations(invoice.id);
  const explanations = new Map(
    (explaining.explained.data?.explanations ?? []).map((explanation) => [
      explanation.rule_id,
      explanation,
    ]),
  );
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
        {rules.length > 0 && <ExplanationsPanel {...explaining} />}
        {rules.map((rule) => (
          <RuleCard
            key={`${rule.severity} ${rule.ruleId}`}
            rule={rule}
            explanation={explanations.get(rule.ruleId)}
          />
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

      <ReportLayers report={report} />
      <BackToTheList />
    </article>
  );
}
