"use client";

import { useQuery } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";

import { RepairStatusBadge, useProposer } from "@/components/repair-parts";
import { RepairSuggestion } from "@/components/repair-suggestion";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Verdict } from "@/components/verdict";
import { Link } from "@/i18n/navigation";
import { formatMoment } from "@/lib/format";
import { repairsQuery } from "@/lib/queries";

/**
 * The repairs proposed for the stored invoice ``invoiceId``, the latest first: who proposed
 * each, where it stands, and what the validator says of the invoice it would leave. With
 * ``offer``, for an invoice whose errors patches could fix, the language model's suggestion.
 */
export function RepairHistory({
  invoiceId,
  offer = false,
}: {
  invoiceId: string;
  offer?: boolean;
}) {
  const t = useTranslations("repairs");
  const locale = useLocale();
  const proposer = useProposer();
  const repairs = useQuery(repairsQuery(invoiceId));

  let content;
  if (repairs.isPending) {
    content = <p className="text-sm text-muted-foreground">{t("loading")}</p>;
  } else if (repairs.isError) {
    content = <p className="text-sm text-muted-foreground">{t("notLoaded")}</p>;
  } else if (repairs.data.length === 0) {
    content = <p className="text-sm text-muted-foreground">{t("none")}</p>;
  } else {
    content = (
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("proposedAt")}</TableHead>
            <TableHead>{t("proposedBy")}</TableHead>
            <TableHead>{t("status")}</TableHead>
            <TableHead>{t("after")}</TableHead>
            <TableHead>{t("patches")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {repairs.data.map((repair) => (
            <TableRow key={repair.id}>
              <TableCell>
                <Link
                  href={`/invoices/${invoiceId}/repairs/${repair.id}`}
                  className="underline underline-offset-4"
                >
                  {formatMoment(locale, repair.proposed_at)}
                </Link>
              </TableCell>
              <TableCell>{proposer(repair)}</TableCell>
              <TableCell>
                <RepairStatusBadge status={repair.status} />
              </TableCell>
              <TableCell>
                <Verdict valid={repair.valid} />
              </TableCell>
              <TableCell className="text-muted-foreground">
                {t("counts", {
                  applied: repair.applied,
                  needsDecision: repair.needs_decision,
                  failed: repair.failed,
                })}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    );
  }
  return (
    <section className="grid gap-3" aria-labelledby="repairs">
      <h2 id="repairs" className="text-lg font-semibold tracking-tight">
        {t("title")}
      </h2>
      {offer && <RepairSuggestion invoiceId={invoiceId} />}
      {content}
    </section>
  );
}
