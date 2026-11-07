"use client";

import { useQuery } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";

import { DiffView } from "@/components/diff-view";
import { Fact } from "@/components/fact";
import { RepairDecision } from "@/components/repair-decision";
import {
  RepairStatusBadge,
  usePerson,
  useProposer,
} from "@/components/repair-parts";
import { ReportLayers, RuleCard } from "@/components/report-rules";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Verdict } from "@/components/verdict";
import { Link } from "@/i18n/navigation";
import { ApiError } from "@/lib/api";
import { formatMoment } from "@/lib/format";
import { repairQuery } from "@/lib/queries";
import type { Outcome, Repair } from "@/lib/repairs";
import { byRule } from "@/lib/report";

/**
 * The repair ``repairId`` of the stored invoice ``invoiceId``: what became of each patch, the
 * difference it makes to the invoice, and the validator's report on the invoice it leaves.
 */
export function RepairView({
  invoiceId,
  repairId,
}: {
  invoiceId: string;
  repairId: string;
}) {
  const t = useTranslations("repair");
  const repair = useQuery(repairQuery(invoiceId, repairId));

  if (repair.isPending) {
    return <p className="text-sm text-muted-foreground">{t("loading")}</p>;
  }
  if (repair.isError) {
    const missing =
      repair.error instanceof ApiError &&
      (repair.error.status === 404 || repair.error.status === 422);
    return (
      <div className="grid gap-4">
        <Alert variant="destructive">
          <AlertDescription>
            {missing ? t("notFound") : t("notLoaded")}
          </AlertDescription>
        </Alert>
        <BackToTheReport invoiceId={invoiceId} />
      </div>
    );
  }
  return <Loaded repair={repair.data} />;
}

function BackToTheReport({ invoiceId }: { invoiceId: string }) {
  const t = useTranslations("repair");
  return (
    <div>
      <Button asChild variant="outline">
        <Link href={`/invoices/${invoiceId}`}>{t("back")}</Link>
      </Button>
    </div>
  );
}

function Loaded({ repair }: { repair: Repair }) {
  const t = useTranslations("repair");
  const locale = useLocale();
  const proposer = useProposer();
  const rules = byRule(repair.report);
  return (
    <article className="grid gap-8">
      <header className="grid gap-4">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold tracking-tight">
            {t("heading", { when: formatMoment(locale, repair.proposed_at) })}
          </h1>
          <RepairStatusBadge status={repair.status} />
        </div>
        <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
          <Fact term={t("proposedBy")} value={proposer(repair)} />
          <Decision repair={repair} />
        </dl>
      </header>

      <section className="grid gap-3" aria-labelledby="patches">
        <h2 id="patches" className="text-lg font-semibold tracking-tight">
          {t("patches")}
        </h2>
        <ul className="grid gap-3">
          {repair.outcomes.map((outcome, index) => (
            <OutcomeItem key={index} outcome={outcome} />
          ))}
        </ul>
        {repair.needs_decision > 0 && (
          <p className="text-sm text-muted-foreground">{t("needsDecision")}</p>
        )}
      </section>

      <section className="grid gap-3" aria-labelledby="diff">
        <h2 id="diff" className="text-lg font-semibold tracking-tight">
          {t("diff")}
        </h2>
        {repair.changed ? (
          <DiffView diff={repair.diff} label={t("diff")} />
        ) : (
          <p className="text-sm text-muted-foreground">{t("unchanged")}</p>
        )}
      </section>

      <section className="grid gap-4" aria-labelledby="after">
        <div className="flex flex-wrap items-center gap-3">
          <h2 id="after" className="text-lg font-semibold tracking-tight">
            {t("reportAfter")}
          </h2>
          <Verdict valid={repair.report.valid} />
        </div>
        {rules.map((rule) => (
          <RuleCard key={`${rule.severity} ${rule.ruleId}`} rule={rule} />
        ))}
      </section>

      <ReportLayers report={repair.report} />
      <RepairDecision repair={repair} />
      <BackToTheReport invoiceId={repair.invoice_id} />
    </article>
  );
}

/**
 * Who decided on the repair, and when; or when it was superseded, by the approval of another
 * repair of the invoice. Nothing while it waits for a decision.
 */
function Decision({ repair }: { repair: Repair }) {
  const t = useTranslations("repair");
  const locale = useLocale();
  const person = usePerson();
  if (repair.decided_at === null) {
    return null;
  }
  const when = formatMoment(locale, repair.decided_at);
  if (repair.status === "approved" || repair.status === "rejected") {
    return (
      <Fact
        term={t(`decidedBy.${repair.status}`)}
        value={t("decision", { who: person(repair.decided_by), when })}
      />
    );
  }
  return <Fact term={t("superseded")} value={t("supersededAt", { when })} />;
}

/** What became of one patch: applied, waiting for a person, or not applied, and why. */
function OutcomeItem({ outcome }: { outcome: Outcome }) {
  const t = useTranslations("repair");
  const { patch } = outcome;
  return (
    <li className="grid gap-2 rounded-lg border p-4 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Badge
          variant={
            outcome.status === "applied"
              ? "success"
              : outcome.status === "failed"
                ? "error"
                : "outline"
          }
        >
          {t(`outcomes.${outcome.status}`)}
        </Badge>
        <span className="font-medium">{t(`ops.${patch.op}`)}</span>
        <code className="font-mono text-xs break-all">{patch.xpath}</code>
      </div>
      {outcome.status === "applied" ? (
        <p>
          {t("change", {
            before: outcome.before ?? t("nothing"),
            after: outcome.after ?? t("nothing"),
          })}
        </p>
      ) : (
        patch.value != null && (
          <p>{t("proposedValue", { value: patch.value })}</p>
        )
      )}
      <p>
        <span className="font-medium">{t("reason")}:</span> {patch.reason}
      </p>
      {outcome.problem && (
        <p lang="en" className="text-muted-foreground">
          {outcome.problem}
        </p>
      )}
    </li>
  );
}
