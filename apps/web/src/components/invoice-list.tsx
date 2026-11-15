"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, FileCheck2 } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";

import { InvoiceFilterBar } from "@/components/invoice-filter-bar";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  NativeSelect,
  NativeSelectOption,
} from "@/components/ui/native-select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Verdict } from "@/components/verdict";
import { useInvoiceFilters } from "@/hooks/use-invoice-filters";
import { Link } from "@/i18n/navigation";
import { formatAmount, formatDay, formatMoment } from "@/lib/format";
import { type Invoice, type InvoiceFilters, PAGE_SIZES } from "@/lib/invoices";
import { invoiceListQuery } from "@/lib/queries";

const FIRST_PAGE = [null];

export function InvoiceList() {
  const t = useTranslations("invoices");
  const facet = useInvoiceFilters();
  const { filters } = facet;
  const view = JSON.stringify(filters);
  const [trail, setTrail] = useState<{
    view: string;
    cursors: (string | null)[];
  }>({
    view,
    cursors: FIRST_PAGE,
  });
  const cursors = trail.view === view ? trail.cursors : FIRST_PAGE;
  if (trail.view !== view) setTrail({ view, cursors: FIRST_PAGE });

  const reversed = Boolean(
    filters.from && filters.to && filters.from > filters.to,
  );
  const active = Boolean(
    facet.search.trim() ||
    filters.q ||
    filters.valid ||
    filters.type ||
    filters.from ||
    filters.to,
  );
  const query = useQuery({
    ...invoiceListQuery(
      filters,
      cursors.at(-1) ?? null,
      (cursors.length - 1) * filters.size,
    ),
    enabled: !reversed,
  });
  const page = query.data;
  const moving = query.isPlaceholderData;

  function turn(next: (string | null)[]) {
    setTrail({ view, cursors: next });
    document
      .getElementById("checked-invoices")
      ?.scrollIntoView({ block: "start" });
  }

  return (
    <div className="grid min-w-0 gap-4">
      <InvoiceFilterBar {...facet} active={active} reversed={reversed} />
      {!reversed && (
        <>
          <p
            role="status"
            aria-live="polite"
            aria-atomic="true"
            className="text-sm text-muted-foreground"
          >
            {moving || query.isPending
              ? t("loading")
              : page
                ? t("resultCount", { count: page.total })
                : ""}
          </p>
          {query.isError && (
            <Alert variant="destructive">
              <AlertDescription>{t("notLoaded")}</AlertDescription>
            </Alert>
          )}
          <div
            aria-busy={moving}
            className={moving ? "min-w-0 opacity-50" : "min-w-0"}
          >
            {page &&
              (page.invoices.length ? (
                <InvoiceTable invoices={page.invoices} search={page.search} />
              ) : (
                <div className="grid justify-items-center gap-3 rounded-xl border border-dashed px-6 py-10 text-center">
                  <span className="grid size-10 place-items-center rounded-full bg-brand/15 text-foreground">
                    <FileCheck2 aria-hidden="true" className="size-5" />
                  </span>
                  <p className="max-w-sm text-sm text-muted-foreground">
                    {active ? t("noMatch") : t("none")}
                  </p>
                  {active && (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={facet.clearFilters}
                    >
                      {t("filters.clear")}
                    </Button>
                  )}
                </div>
              ))}
          </div>
          {(page || cursors.length > 1) && (
            <nav
              aria-label={t("pages.label")}
              className="flex flex-wrap items-center justify-between gap-x-4 gap-y-3"
            >
              <div className="flex items-center gap-2">
                <Label htmlFor="invoice-page-size">{t("pages.size")}</Label>
                <NativeSelect
                  id="invoice-page-size"
                  size="sm"
                  value={filters.size}
                  onChange={(event) =>
                    facet.setFilters({
                      size: Number(
                        event.currentTarget.value,
                      ) as InvoiceFilters["size"],
                    })
                  }
                >
                  {PAGE_SIZES.map((size) => (
                    <NativeSelectOption key={size} value={size}>
                      {size}
                    </NativeSelectOption>
                  ))}
                </NativeSelect>
              </div>
              <div className="flex flex-wrap items-center gap-2 sm:gap-3">
                {page && (
                  <span className="text-sm text-muted-foreground tabular-nums">
                    {t("pages.range", {
                      first: page.invoices.length ? page.offset + 1 : 0,
                      last: page.invoices.length
                        ? page.offset + page.invoices.length
                        : 0,
                      total: page.total,
                    })}
                  </span>
                )}
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={cursors.length < 2 || moving}
                  onClick={() => turn(cursors.slice(0, -1))}
                >
                  <ChevronLeft aria-hidden="true" />
                  {t("pages.previous")}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={!page?.next || moving}
                  onClick={() => page?.next && turn([...cursors, page.next])}
                >
                  {t("pages.next")}
                  <ChevronRight aria-hidden="true" />
                </Button>
              </div>
            </nav>
          )}
        </>
      )}
    </div>
  );
}

function InvoiceTable({
  invoices,
  search,
}: {
  invoices: Invoice[];
  search: string;
}) {
  const t = useTranslations("invoices");
  const locale = useLocale();
  return (
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
          {invoices.map((invoice) => (
            <InvoiceRow
              key={invoice.id}
              invoice={invoice}
              locale={locale}
              search={search}
            />
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function Highlight({ text, search }: { text: string; search: string }) {
  if (!search) return text;
  const literal = search.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return text.split(new RegExp(`(${literal})`, "iu")).map((part, index) =>
    index % 2 ? (
      <mark key={index} className="rounded-sm bg-brand/20 text-inherit">
        {part}
      </mark>
    ) : (
      part
    ),
  );
}

function InvoiceRow({
  invoice,
  locale,
  search,
}: {
  invoice: Invoice;
  locale: string;
  search: string;
}) {
  const t = useTranslations("invoices");
  const summary = invoice.summary;
  return (
    <TableRow>
      <TableCell className="font-medium">
        <Link
          href={`/invoices/${invoice.id}`}
          className="underline-offset-4 hover:underline"
        >
          {summary ? (
            <Highlight text={summary.number} search={search} />
          ) : (
            t("notSchemaValid")
          )}
        </Link>
      </TableCell>
      <TableCell className="max-w-64 truncate">
        {summary ? (
          <>
            <Highlight text={summary.seller ?? "—"} search={search} />
            {" → "}
            <Highlight text={summary.buyer ?? "—"} search={search} />
          </>
        ) : (
          "—"
        )}
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
