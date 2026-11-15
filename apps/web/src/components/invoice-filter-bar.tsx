"use client";

import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  NativeSelect,
  NativeSelectOption,
} from "@/components/ui/native-select";
import type { useInvoiceFilters } from "@/hooks/use-invoice-filters";
import type { InvoiceFilters } from "@/lib/invoices";

interface Props extends ReturnType<typeof useInvoiceFilters> {
  active: boolean;
  reversed: boolean;
}

export function InvoiceFilterBar({
  filters,
  search,
  setSearch,
  setFilters,
  clearSearch,
  clearFilters,
  active,
  reversed,
}: Props) {
  const t = useTranslations("invoices.filters");
  return (
    <div className="grid gap-3">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-[minmax(0,1.8fr)_minmax(0,1fr)_minmax(0,1.4fr)_repeat(2,minmax(0,1.2fr))]">
        <div className="col-span-2 grid min-w-0 gap-2 md:col-span-1">
          <Label htmlFor="invoice-search">{t("search")}</Label>
          <Input
            id="invoice-search"
            type="search"
            placeholder={t("placeholder")}
            value={search}
            maxLength={100}
            onChange={(event) => setSearch(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.preventDefault();
                clearSearch();
              }
            }}
          />
        </div>
        <div className="grid min-w-0 gap-2 [&_[data-slot=native-select-wrapper]]:w-full">
          <Label htmlFor="invoice-verdict">{t("verdict")}</Label>
          <NativeSelect
            id="invoice-verdict"
            value={filters.valid}
            onChange={(event) =>
              setFilters({
                valid: event.currentTarget.value as InvoiceFilters["valid"],
              })
            }
          >
            <NativeSelectOption value="">{t("all")}</NativeSelectOption>
            <NativeSelectOption value="true">{t("valid")}</NativeSelectOption>
            <NativeSelectOption value="false">
              {t("invalid")}
            </NativeSelectOption>
          </NativeSelect>
        </div>
        <div className="grid min-w-0 gap-2 [&_[data-slot=native-select-wrapper]]:w-full">
          <Label htmlFor="invoice-type">{t("type")}</Label>
          <NativeSelect
            id="invoice-type"
            value={filters.type}
            onChange={(event) =>
              setFilters({
                type: event.currentTarget.value as InvoiceFilters["type"],
              })
            }
          >
            <NativeSelectOption value="">{t("all")}</NativeSelectOption>
            <NativeSelectOption value="Invoice">
              {t("invoice")}
            </NativeSelectOption>
            <NativeSelectOption value="CreditNote">
              {t("creditNote")}
            </NativeSelectOption>
          </NativeSelect>
        </div>
        {(["from", "to"] as const).map((end) => (
          <div key={end} className="grid min-w-0 gap-2">
            <Label htmlFor={`invoice-${end}`}>{t(end)}</Label>
            <Input
              id={`invoice-${end}`}
              type="date"
              value={filters[end]}
              aria-invalid={reversed || undefined}
              aria-describedby={reversed ? "invoice-date-range" : undefined}
              onChange={(event) =>
                setFilters({ [end]: event.currentTarget.value })
              }
            />
          </div>
        ))}
      </div>
      {reversed && (
        <p
          id="invoice-date-range"
          role="alert"
          className="text-sm text-destructive"
        >
          {t("dateOrder")}
        </p>
      )}
      {active && (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="justify-self-start"
          onClick={clearFilters}
        >
          {t("clear")}
        </Button>
      )}
    </div>
  );
}
