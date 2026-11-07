"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { FileCheck2 } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Verdict } from "@/components/verdict";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Link } from "@/i18n/navigation";
import { formatAmount, formatDay, formatMoment } from "@/lib/format";
import type { Invoice } from "@/lib/invoices";
import { invoicesQuery } from "@/lib/queries";

/** The organization's invoices, the newest first, a page at a time. */
export function InvoiceList() {
  const t = useTranslations("invoices");
  const locale = useLocale();
  const invoices = useInfiniteQuery(invoicesQuery);

  if (invoices.isPending) {
    return <p className="text-sm text-muted-foreground">{t("loading")}</p>;
  }
  if (invoices.isError) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{t("notLoaded")}</AlertDescription>
      </Alert>
    );
  }
  const all = invoices.data.pages.flatMap((page) => page.invoices);
  if (all.length === 0) {
    return (
      <div className="grid justify-items-center gap-3 rounded-xl border border-dashed px-6 py-10 text-center">
        <span className="grid size-10 place-items-center rounded-full bg-brand/15 text-foreground">
          <FileCheck2 aria-hidden="true" className="size-5" />
        </span>
        <p className="max-w-sm text-sm text-muted-foreground">{t("none")}</p>
      </div>
    );
  }
  return (
    <div className="grid gap-4">
      <div className="overflow-hidden rounded-xl border bg-card text-card-foreground shadow-sm">
        <Table>
          <TableHeader className="bg-muted/50">
            <TableRow>
              <TableHead>{t("number")}</TableHead>
              <TableHead>{t("parties")}</TableHead>
              <TableHead>{t("issued")}</TableHead>
              <TableHead className="text-right">{t("amount")}</TableHead>
              <TableHead>{t("verdict")}</TableHead>
              <TableHead>{t("submitted")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {all.map((invoice) => (
              <InvoiceRow key={invoice.id} invoice={invoice} locale={locale} />
            ))}
          </TableBody>
        </Table>
      </div>
      {invoices.hasNextPage && (
        <div>
          <Button
            variant="outline"
            disabled={invoices.isFetchingNextPage}
            onClick={() => void invoices.fetchNextPage()}
          >
            {t("more")}
          </Button>
        </div>
      )}
    </div>
  );
}

function InvoiceRow({ invoice, locale }: { invoice: Invoice; locale: string }) {
  const t = useTranslations("invoices");
  const summary = invoice.summary;
  return (
    <TableRow>
      <TableCell className="font-medium">
        <Link
          href={`/invoices/${invoice.id}`}
          className="underline-offset-4 hover:underline"
        >
          {summary?.number ?? t("unreadable")}
        </Link>
      </TableCell>
      <TableCell className="max-w-64 truncate">
        {summary ? `${summary.seller ?? "—"} → ${summary.buyer ?? "—"}` : "—"}
      </TableCell>
      <TableCell>
        {summary ? formatDay(locale, summary.issue_date) : "—"}
      </TableCell>
      <TableCell className="text-right tabular-nums">
        {summary
          ? formatAmount(locale, summary.payable_amount, summary.currency)
          : "—"}
      </TableCell>
      <TableCell>
        <Verdict valid={invoice.valid} />
      </TableCell>
      <TableCell className="text-muted-foreground">
        {formatMoment(locale, invoice.submitted_at)}
      </TableCell>
    </TableRow>
  );
}
