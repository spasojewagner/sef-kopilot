"use client";

import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useRouter } from "@/i18n/navigation";
import { type InvoiceFilters, PAGE_SIZE, PAGE_SIZES } from "@/lib/invoices";

const SEARCH_DELAY = 300;

export const EMPTY_FILTERS: InvoiceFilters = {
  q: "",
  valid: "",
  type: "",
  from: "",
  to: "",
  size: PAGE_SIZE,
};

function readDate(value: string | null): string {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return "";
  const date = new Date(`${value}T00:00:00Z`);
  return !isNaN(date.getTime()) && date.toISOString().startsWith(value)
    ? value
    : "";
}

function readFilters(query: string): InvoiceFilters {
  const params = new URLSearchParams(query);
  const valid = params.get("valid");
  const type = params.get("type");
  return {
    q: (params.get("q") ?? "").trim().slice(0, 100),
    valid: valid === "true" || valid === "false" ? valid : "",
    type: type === "Invoice" || type === "CreditNote" ? type : "",
    from: readDate(params.get("from")),
    to: readDate(params.get("to")),
    size:
      PAGE_SIZES.find((size) => String(size) === params.get("size")) ??
      PAGE_SIZE,
  };
}

function writeFilters(query: string, filters: InvoiceFilters): string {
  const params = new URLSearchParams(query);
  for (const key of ["q", "valid", "type", "from", "to"] as const) {
    if (filters[key]) params.set(key, filters[key]);
    else params.delete(key);
  }
  if (filters.size === PAGE_SIZE) params.delete("size");
  else params.set("size", String(filters.size));
  return params.toString();
}

export function useInvoiceFilters() {
  const query = useSearchParams().toString();
  const router = useRouter();
  const filters = useMemo(() => readFilters(query), [query]);
  const [draft, setDraft] = useState({ source: filters.q, text: filters.q });
  if (draft.source !== filters.q) {
    setDraft({ source: filters.q, text: filters.q });
  }

  const replace = useCallback(
    (next: InvoiceFilters) => {
      const updated = writeFilters(query, next);
      if (updated === query) return;
      // Keep the previous URL in history while replacing the active entry with the new filters.
      window.history.pushState(null, "", window.location.href);
      router.replace(updated ? `/invoices?${updated}` : "/invoices", {
        scroll: false,
      });
    },
    [query, router],
  );

  const search = draft.source === filters.q ? draft.text : filters.q;
  useEffect(() => {
    const q = search.trim();
    if (q === filters.q) return;
    const timer = window.setTimeout(
      () => replace({ ...filters, q }),
      SEARCH_DELAY,
    );
    return () => window.clearTimeout(timer);
  }, [search, filters, replace]);

  return {
    filters,
    search,
    setSearch: (text: string) => setDraft({ source: filters.q, text }),
    setFilters: (changes: Partial<InvoiceFilters>) =>
      replace({ ...filters, ...changes }),
    clearSearch: () => {
      setDraft({ source: filters.q, text: "" });
      if (filters.q) replace({ ...filters, q: "" });
    },
    clearFilters: () => {
      setDraft({ source: filters.q, text: "" });
      replace({ ...EMPTY_FILTERS, size: filters.size });
    },
  };
}
