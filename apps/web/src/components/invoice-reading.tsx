"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  CircleAlert,
  CircleCheck,
  CircleDashed,
  FileText,
  Info,
  Plus,
  Trash2,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useId, useState, type ReactNode } from "react";

import { useUploadErrorMessage } from "@/components/upload-errors";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  NativeSelect,
  NativeSelectOption,
} from "@/components/ui/native-select";
import { useRouter } from "@/i18n/navigation";
import { ApiError } from "@/lib/api";
import { formatAmount, formatDay } from "@/lib/format";
import {
  draftFileName,
  draftInvoice,
  emptyLine,
  emptyVatRow,
  fieldsOf,
  formOf,
  missingIn,
  requiredIn,
  TYPE_CODES,
  VAT_CATEGORIES,
  type DocumentType,
  type Extraction,
  type FieldsForm,
  type LineForm,
  type Needed,
  type PartyForm,
  type Required,
  type TotalsForm,
  type VatForm,
} from "@/lib/extraction";
import { storeInvoice, validateInvoice, type Profile } from "@/lib/invoices";
import { invoiceQuery, invoiceListKey } from "@/lib/queries";

/** The label of each field SEF needs, and the party it belongs to, if any. */
const NEEDED_LABEL: Record<
  Exclude<Needed, "lines">,
  [
    (
      | "type_code"
      | "number"
      | "issue_date"
      | "currency"
      | "name"
      | "tax_id"
      | "payable"
    ),
    "seller" | "buyer" | null,
  ]
> = {
  type_code: ["type_code", null],
  number: ["number", null],
  issue_date: ["issue_date", null],
  currency: ["currency", null],
  "seller.name": ["name", "seller"],
  "seller.tax_id": ["tax_id", "seller"],
  "buyer.name": ["name", "buyer"],
  "buyer.tax_id": ["tax_id", "buyer"],
  "totals.payable": ["payable", null],
};

/** The label of each field the invoice cannot be made without that is not a line's or a row's. */
const REQUIRED_LABEL = {
  type_code: "type_code",
  number: "number",
  issue_date: "issue_date",
  "totals.tax": "tax",
  "totals.payable": "payable",
} as const satisfies Partial<Record<Required, string>>;

/** A text field of the form: its label, and whether SEF needs what it leaves empty. */
function Field({
  label,
  value,
  onChange,
  needed = false,
  hint,
  numeric = false,
  className,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  needed?: boolean;
  hint?: string;
  numeric?: boolean;
  className?: string;
}) {
  const id = useId();
  const missing = needed && value.trim() === "";
  return (
    <div className={`grid content-start gap-1.5 ${className ?? ""}`}>
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={hint}
        inputMode={numeric ? "decimal" : undefined}
        aria-invalid={missing || undefined}
      />
    </div>
  );
}

/** The panels of the form, in its order. */
type PanelName =
  "invoice" | "seller" | "buyer" | "lines" | "vat" | "totals" | "payment";

/**
 * A group of fields that folds away under a line of its own: its title, what it holds in a few
 * words, and whether something in it needs the person. Its fields stay a group named by its
 * title, folded or not.
 */
function Panel({
  title,
  summary,
  attention,
  open,
  onOpenChange,
  children,
}: {
  title: string;
  summary: string | null;
  attention: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: ReactNode;
}) {
  const t = useTranslations("reading");
  return (
    <details
      open={open}
      onToggle={(event) => {
        if (event.currentTarget.open !== open) {
          onOpenChange(event.currentTarget.open);
        }
      }}
      className="disclosure group/panel rounded-lg border bg-card"
    >
      <summary className="flex cursor-pointer list-none items-center gap-3 rounded-lg px-4 py-3 outline-none hover:bg-muted/40 focus-visible:ring-[3px] focus-visible:ring-ring/50 [&::-webkit-details-marker]:hidden">
        {attention ? (
          <CircleAlert
            role="img"
            aria-label={t("panel.attention")}
            className="size-4 shrink-0 text-warning"
          />
        ) : summary === null ? (
          <CircleDashed
            role="img"
            aria-label={t("panel.empty")}
            className="size-4 shrink-0 text-muted-foreground"
          />
        ) : (
          <CircleCheck
            role="img"
            aria-label={t("panel.read")}
            className="size-4 shrink-0 text-success"
          />
        )}
        <span className="grid min-w-0 flex-1 gap-0.5">
          <span className="text-sm font-semibold">{title}</span>
          <span className="truncate text-sm text-muted-foreground">
            {summary ?? t("panel.empty")}
          </span>
        </span>
        <ChevronDown
          aria-hidden="true"
          className="size-4 shrink-0 text-muted-foreground transition-transform group-open/panel:rotate-180"
        />
      </summary>
      <fieldset className="grid gap-4 border-t px-3 pt-4 pb-5 sm:px-4">
        <legend className="sr-only">{title}</legend>
        {children}
      </fieldset>
    </details>
  );
}

/**
 * The columns of a line or a row: its number, what it is, its amount, and its chevron. On a
 * phone the amount goes under what it is, which then has the width to be read.
 */
const ROW_COLUMNS =
  "grid-cols-[1.25rem_minmax(0,1fr)_1rem] sm:grid-cols-[1.5rem_minmax(0,1fr)_auto_1rem]";
/** Where the amount of a line or a row goes, under what it is on a phone. */
const ROW_AMOUNT =
  "col-start-2 row-start-2 font-medium tabular-nums sm:col-start-3 sm:row-start-1 sm:text-right";

/**
 * A line or a row of the recapitulation: what it holds, on one line in columns, which opens on
 * its fields.
 */
function Row({
  cells,
  open,
  onOpenChange,
  children,
}: {
  cells: ReactNode;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: ReactNode;
}) {
  return (
    <details
      open={open}
      onToggle={(event) => {
        if (event.currentTarget.open !== open) {
          onOpenChange(event.currentTarget.open);
        }
      }}
      className="disclosure group/row rounded-md border open:bg-muted/20"
    >
      <summary
        className={`grid cursor-pointer list-none items-center gap-x-2 gap-y-1 rounded-md px-2.5 py-2 text-sm outline-none hover:bg-muted/40 focus-visible:ring-[3px] focus-visible:ring-ring/50 sm:gap-x-3 sm:px-3 [&::-webkit-details-marker]:hidden ${ROW_COLUMNS}`}
      >
        {cells}
        <ChevronDown
          aria-hidden="true"
          className="col-start-3 row-start-1 size-4 text-muted-foreground transition-transform group-open/row:rotate-180 sm:col-start-4"
        />
      </summary>
      <div className="grid gap-3 border-t px-2.5 pt-3 pb-4 sm:px-3">
        {children}
      </div>
    </details>
  );
}

/**
 * The document beside the fields, at the address of its bytes in this page: a picture, or a PDF
 * in the browser's own viewer.
 */
function DocumentShown({ url, type }: { url: string; type: DocumentType }) {
  const t = useTranslations("reading");
  if (type === "application/pdf") {
    return (
      <div className="grid gap-2">
        {/* A browser without a viewer of its own, on a phone say, shows what is inside. */}
        <object
          data={url}
          type="application/pdf"
          aria-label={t("documentAlt")}
          className="h-[50vh] w-full rounded-md border bg-muted/40 lg:h-[70vh]"
        >
          <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
            <FileText aria-hidden className="size-8 text-muted-foreground" />
            <p className="max-w-xs text-sm text-muted-foreground">
              {t("pdfNotShown")}
            </p>
            <Button asChild variant="outline" size="sm">
              <a href={url} target="_blank" rel="noreferrer">
                {t("openPdf")}
              </a>
            </Button>
          </div>
        </object>
        <a
          href={url}
          target="_blank"
          rel="noreferrer"
          className="justify-self-start text-sm text-muted-foreground underline underline-offset-4 hover:text-foreground"
        >
          {t("openPdf")}
        </a>
      </div>
    );
  }
  return (
    // Opened at its full size in a tab of its own, which on a phone is where it can be read.
    <a
      href={url}
      target="_blank"
      rel="noreferrer"
      className="block cursor-zoom-in rounded-md focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
    >
      {/* A picture the visitor chose, shown as it is: next/image would send it to a server. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={url}
        alt={t("documentAlt")}
        className="w-full rounded-md border bg-muted/40 object-contain lg:max-h-[calc(100vh-8rem)]"
      />
    </a>
  );
}

/**
 * An invoice read from a PDF or a picture (ADR-0062, beta), for the visitor to check before it
 * is made: the document beside the fields the model read, every one of them editable. The
 * fields SEF needs and the model did not find are named and marked. Making the invoice has the
 * API draft its UBL of the fields, in code, then stores and validates it as an upload does, and
 * shows its report; or the drafted XML is downloaded, once the validator passes it. Nothing is
 * kept until the invoice is made. The document itself can be downloaded again as it was
 * chosen, under its own name.
 */
export function InvoiceReading({
  url,
  name,
  type,
  extraction,
  profile,
  onDiscard,
}: {
  url: string;
  name: string;
  type: DocumentType;
  extraction: Extraction;
  profile: Profile;
  onDiscard: () => void;
}) {
  const t = useTranslations("reading");
  const messageFor = useUploadErrorMessage();
  const router = useRouter();
  const client = useQueryClient();
  const [form, setForm] = useState<FieldsForm>(() => formOf(extraction.fields));
  const missing = missingIn(form);
  const needs = new Set<Needed>(missing);
  const required = requiredIn(form);
  // Asked to make or download the invoice without what it cannot be made without: those
  // fields are named and marked from then on, as they are left empty.
  const [refusedEmpty, setRefusedEmpty] = useState(false);
  const lacking = new Set<Required>(refusedEmpty ? required : []);
  const whenComplete = (action: () => void) => () => {
    if (required.length > 0) {
      setRefusedEmpty(true);
      return;
    }
    action();
  };

  const making = useMutation({
    mutationFn: async () =>
      storeInvoice(
        new Blob([await drafted(form)], { type: "application/xml" }),
        profile,
      ),
    onSuccess: (stored) => {
      client.setQueryData(invoiceQuery(stored.id).queryKey, stored);
      void client.invalidateQueries({ queryKey: invoiceListKey });
      router.push(`/invoices/${stored.id}`);
    },
  });
  // The draft is checked before it is downloaded, and kept from the person while it fails: a
  // file that SEF refuses is no use to them. The report says why; nothing is stored.
  const downloading = useMutation({
    mutationFn: async () => {
      const xml = await drafted(form);
      return { form, report: await validateInvoice(xml, profile), xml };
    },
    onSuccess: ({ form: checked, report, xml }) => {
      if (!report.valid) {
        return;
      }
      const url = URL.createObjectURL(
        new Blob([xml], { type: "application/xml" }),
      );
      const link = window.document.createElement("a");
      link.href = url;
      link.download = draftFileName(checked);
      link.click();
      URL.revokeObjectURL(url);
    },
  });
  const make = whenComplete(() => making.mutate());
  const download = whenComplete(() => downloading.mutate());
  const failed = making.error ?? downloading.error;
  const busy = making.isPending || downloading.isPending;
  // The report on the fields as they are: one on fields since changed says nothing of them.
  const refused =
    downloading.data?.form === form && !downloading.data.report.valid
      ? downloading.data.report.violations.filter(
          ({ severity }) => severity === "fatal",
        )
      : null;

  const set = (key: keyof FieldsForm) => (value: string) =>
    setForm((was) => ({ ...was, [key]: value }));
  const setParty =
    (party: "seller" | "buyer", key: keyof PartyForm) => (value: string) =>
      setForm((was) => ({ ...was, [party]: { ...was[party], [key]: value } }));
  const setTotal = (key: keyof TotalsForm) => (value: string) =>
    setForm((was) => ({ ...was, totals: { ...was.totals, [key]: value } }));
  const setPayment = (key: keyof FieldsForm["payment"]) => (value: string) =>
    setForm((was) => ({ ...was, payment: { ...was.payment, [key]: value } }));
  const setLine = (index: number, key: keyof LineForm) => (value: string) =>
    setForm((was) => ({
      ...was,
      lines: was.lines.map((line, at) =>
        at === index ? { ...line, [key]: value } : line,
      ),
    }));
  const setVat = (index: number, key: keyof VatForm) => (value: string) =>
    setForm((was) => ({
      ...was,
      vat_breakdown: was.vat_breakdown.map((row, at) =>
        at === index ? { ...row, [key]: value } : row,
      ),
    }));

  function requiredLabel(name: Required): string {
    const [, at] = name.split(".");
    if (name === "lines") {
      return t("sections.lines");
    }
    if (name.startsWith("lines.")) {
      return `${t("fields.net_amount")} (${t("line", { number: Number(at) + 1 })})`;
    }
    if (name.startsWith("vat_breakdown.")) {
      return `${t("fields.tax_amount")} (${t("sections.vat")}, ${t("vatRow", { number: Number(at) + 1 })})`;
    }
    return t(`fields.${REQUIRED_LABEL[name as keyof typeof REQUIRED_LABEL]}`);
  }

  const locale = useLocale();
  const currency = /^[A-Z]{3}$/.test(form.currency.trim())
    ? form.currency.trim()
    : null;
  /** An amount as the person's language writes it, in the invoice's currency; as typed if not one. */
  const shownAmount = (value: string, inCurrency = true) => {
    const plain = value.trim();
    if (!/^-?\d+(\.\d+)?$/.test(plain)) {
      return plain;
    }
    try {
      return formatAmount(locale, plain, inCurrency ? currency : null);
    } catch {
      return formatAmount(locale, plain, null);
    }
  };
  /** A day as the person's language writes it; as typed if not one. */
  const shownDay = (value: string) => {
    const plain = value.trim();
    return /^\d{4}-\d{2}-\d{2}$/.test(plain) && !Number.isNaN(Date.parse(plain))
      ? formatDay(locale, plain)
      : plain;
  };
  const joined = (...parts: (string | false | null | undefined)[]) =>
    parts.filter((part) => part).join(" · ") || null;
  const vatRate = (rate: string) => rate.trim() && `${rate.trim()} %`;

  // A panel needs the person where SEF needs a field of it the reading did not find, or where
  // the invoice cannot be made without one: it opens of itself then, and stays as they leave it.
  const lackingAny = (prefix: string) =>
    [...lacking].some((name) => name.startsWith(prefix));
  const attention: Record<PanelName, boolean> = {
    invoice:
      (["type_code", "number", "issue_date", "currency"] as const).some(
        (name) => needs.has(name),
      ) ||
      lacking.has("type_code") ||
      lacking.has("number") ||
      lacking.has("issue_date"),
    seller: needs.has("seller.name") || needs.has("seller.tax_id"),
    buyer: needs.has("buyer.name") || needs.has("buyer.tax_id"),
    lines: needs.has("lines") || lackingAny("lines"),
    vat: lackingAny("vat_breakdown."),
    totals: needs.has("totals.payable") || lackingAny("totals."),
    payment: false,
  };
  const [opened, setOpened] = useState(() => attention);
  const panel = (name: PanelName) => ({
    attention: attention[name],
    open: opened[name] || (refusedEmpty && attention[name]),
    onOpenChange: (open: boolean) =>
      setOpened((was) => ({ ...was, [name]: open })),
  });
  // The lines and rows open on their fields: a new one, and one the invoice cannot be made
  // without a field of.
  const [openLines, setOpenLines] = useState<ReadonlySet<number>>(
    () =>
      new Set(
        form.lines.flatMap((line, index) =>
          line.net_amount.trim() === "" ? [index] : [],
        ),
      ),
  );
  const [openRows, setOpenRows] = useState<ReadonlySet<number>>(new Set());
  const toggled =
    (
      set: (change: (was: ReadonlySet<number>) => ReadonlySet<number>) => void,
      index: number,
    ) =>
    (open: boolean) =>
      set((was) => {
        const next = new Set(was);
        if (open) {
          next.add(index);
        } else {
          next.delete(index);
        }
        return next;
      });
  /** The indexes still open once ``removed`` is gone, those after it one less. */
  const without = (was: ReadonlySet<number>, removed: number) =>
    new Set(
      [...was]
        .filter((index) => index !== removed)
        .map((index) => (index > removed ? index - 1 : index)),
    );
  const typeName = TYPE_CODES.includes(
    form.type_code as (typeof TYPE_CODES)[number],
  )
    ? t(`types.${form.type_code as (typeof TYPE_CODES)[number]}`)
    : null;

  function party(which: "seller" | "buyer") {
    const values = form[which];
    const needed = (key: keyof PartyForm) =>
      needs.has(`${which}.${key}` as Needed);
    return (
      <Panel
        title={t(`sections.${which}`)}
        summary={joined(
          values.name.trim(),
          values.tax_id.trim() &&
            `${t("fields.tax_id")} ${values.tax_id.trim()}`,
          values.city.trim(),
        )}
        {...panel(which)}
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label={t("fields.name")}
            value={values.name}
            onChange={setParty(which, "name")}
            needed={needed("name")}
            className="sm:col-span-2"
          />
          <Field
            label={t("fields.tax_id")}
            value={values.tax_id}
            onChange={setParty(which, "tax_id")}
            needed={needed("tax_id")}
            numeric
          />
          <Field
            label={t("fields.company_id")}
            value={values.company_id}
            onChange={setParty(which, "company_id")}
            numeric
          />
          <Field
            label={t("fields.street")}
            value={values.street}
            onChange={setParty(which, "street")}
            className="sm:col-span-2"
          />
          <Field
            label={t("fields.postal_code")}
            value={values.postal_code}
            onChange={setParty(which, "postal_code")}
            numeric
          />
          <Field
            label={t("fields.city")}
            value={values.city}
            onChange={setParty(which, "city")}
          />
          <Field
            label={t("fields.country")}
            value={values.country}
            onChange={setParty(which, "country")}
            hint={t("hints.country")}
          />
          {which === "seller" ? (
            <>
              <Field
                label={t("fields.email")}
                value={values.email}
                onChange={setParty(which, "email")}
              />
              <Choice
                label={t("fields.seller_in_vat_register")}
                value={form.seller_in_vat_register}
                onChange={set("seller_in_vat_register")}
                options={[
                  ["yes", t("registered.yes")],
                  ["no", t("registered.no")],
                ]}
              />
            </>
          ) : null}
        </div>
      </Panel>
    );
  }

  const totalsShown = (
    [
      "line_total",
      "tax_exclusive",
      "tax",
      "tax_inclusive",
      "prepaid",
      "payable",
    ] as const
  ).map((key) => (
    <Field
      key={key}
      label={t(`fields.${key}`)}
      value={form.totals[key]}
      onChange={setTotal(key)}
      needed={
        (key === "payable" && needs.has("totals.payable")) ||
        (key === "tax" && lacking.has("totals.tax"))
      }
      hint={t("hints.amount")}
      numeric
    />
  ));
  const unread = <span className="text-muted-foreground">—</span>;

  return (
    <div className="grid gap-6">
      <div className="grid gap-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-lg font-semibold tracking-tight">
            {t("title", {
              kind: type === "application/pdf" ? "pdf" : "picture",
            })}
          </h3>
          <Badge variant="warning">{t("beta")}</Badge>
        </div>
        <p className="text-sm text-muted-foreground">
          {t("model", { model: extraction.model })}
        </p>
        <p
          role="note"
          className="flex max-w-prose gap-2 text-sm text-muted-foreground"
        >
          <Info aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          <span>{t("check")}</span>
        </p>
      </div>
      <div className="grid items-start gap-8 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <section aria-label={t("document")} className="lg:sticky lg:top-24">
          <DocumentShown url={url} type={type} />
          <Button asChild variant="outline" size="sm" className="mt-3">
            <a href={url} download={name}>
              {t("downloadOriginal")}
            </a>
          </Button>
        </section>
        <form
          className="grid gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            make();
          }}
        >
          <section
            aria-label={t("summary.label")}
            className="grid gap-4 rounded-lg border bg-card p-5"
          >
            <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
              <div className="grid min-w-0 gap-0.5">
                <p className="text-sm text-muted-foreground">
                  {typeName ?? t("summary.untyped")}
                </p>
                <p className="text-xl font-semibold tracking-tight break-all">
                  {form.number.trim() || t("summary.unnumbered")}
                </p>
                {form.issue_date.trim() ? (
                  <p className="text-sm text-muted-foreground">
                    {t("summary.issued", {
                      date: shownDay(form.issue_date),
                    })}
                  </p>
                ) : null}
              </div>
              <div className="grid gap-0.5 sm:text-right">
                <p className="text-sm text-muted-foreground">
                  {t("fields.payable")}
                </p>
                <p className="text-2xl font-semibold tracking-tight tabular-nums">
                  {form.totals.payable.trim()
                    ? shownAmount(form.totals.payable)
                    : unread}
                </p>
                {form.totals.tax_exclusive.trim() ? (
                  <p className="text-sm text-muted-foreground tabular-nums">
                    {t("summary.net", {
                      amount: shownAmount(form.totals.tax_exclusive),
                    })}
                  </p>
                ) : null}
                {form.totals.tax.trim() ? (
                  <p className="text-sm text-muted-foreground tabular-nums">
                    {t("summary.tax", { amount: shownAmount(form.totals.tax) })}
                  </p>
                ) : null}
              </div>
            </div>
            <dl className="grid gap-3 border-t pt-4 text-sm sm:grid-cols-2">
              {(["seller", "buyer"] as const).map((which) => (
                <div key={which} className="grid min-w-0 gap-0.5">
                  <dt className="text-muted-foreground">
                    {t(`sections.${which}`)}
                  </dt>
                  <dd className="truncate font-medium">
                    {form[which].name.trim() || unread}
                  </dd>
                  {form[which].tax_id.trim() ? (
                    <dd className="text-muted-foreground tabular-nums">
                      {t("fields.tax_id")} {form[which].tax_id.trim()}
                    </dd>
                  ) : needs.has(`${which}.tax_id`) ? (
                    <dd className="text-warning">{t("summary.noTaxId")}</dd>
                  ) : null}
                </div>
              ))}
            </dl>
            {missing.length > 0 ? (
              <Alert role="status" variant="warning">
                <CircleAlert aria-hidden="true" />
                <AlertTitle className="line-clamp-none">
                  {t("missingTitle")}
                </AlertTitle>
                <AlertDescription>
                  {t("missingList", {
                    fields: missing
                      .map((name) => {
                        if (name === "lines") {
                          return t("sections.lines");
                        }
                        const [label, party] = NEEDED_LABEL[name];
                        return party === null
                          ? t(`fields.${label}`)
                          : `${t(`fields.${label}`)} (${t(`sections.${party}`)})`;
                      })
                      .join(", "),
                  })}
                </AlertDescription>
              </Alert>
            ) : (
              <p className="flex items-center gap-2 text-sm text-success">
                <CircleCheck aria-hidden="true" className="size-4 shrink-0" />
                {t("summary.complete")}
              </p>
            )}
          </section>

          <Panel
            title={t("sections.invoice")}
            summary={joined(
              typeName,
              form.number.trim(),
              shownDay(form.issue_date),
              form.currency.trim(),
            )}
            {...panel("invoice")}
          >
            <div className="grid gap-4 sm:grid-cols-2">
              <Choice
                label={t("fields.type_code")}
                value={form.type_code}
                onChange={set("type_code")}
                needed={needs.has("type_code")}
                options={TYPE_CODES.map((code) => [code, t(`types.${code}`)])}
              />
              <Field
                label={t("fields.number")}
                value={form.number}
                onChange={set("number")}
                needed={needs.has("number")}
              />
              <Field
                label={t("fields.issue_date")}
                value={form.issue_date}
                onChange={set("issue_date")}
                needed={needs.has("issue_date")}
                hint={t("hints.date")}
              />
              <Field
                label={t("fields.due_date")}
                value={form.due_date}
                onChange={set("due_date")}
                hint={t("hints.date")}
              />
              <Field
                label={t("fields.delivery_date")}
                value={form.delivery_date}
                onChange={set("delivery_date")}
                hint={t("hints.date")}
              />
              <Field
                label={t("fields.currency")}
                value={form.currency}
                onChange={set("currency")}
                needed={needs.has("currency")}
              />
              <Field
                label={t("fields.buyer_reference")}
                value={form.buyer_reference}
                onChange={set("buyer_reference")}
                className="sm:col-span-2"
              />
            </div>
          </Panel>

          {party("seller")}
          {party("buyer")}

          <Panel
            title={t("sections.lines")}
            summary={joined(
              t("linesCount", { count: form.lines.length }),
              form.totals.line_total.trim() &&
                shownAmount(form.totals.line_total),
            )}
            {...panel("lines")}
          >
            {form.lines.length === 0 ? (
              <p
                className={
                  needs.has("lines")
                    ? "text-sm text-destructive"
                    : "text-sm text-muted-foreground"
                }
              >
                {t("noLines")}
              </p>
            ) : (
              <div
                aria-hidden="true"
                className="hidden grid-cols-[1.5rem_minmax(0,1fr)_auto_1rem] gap-x-3 px-3 text-xs text-muted-foreground sm:grid"
              >
                <span />
                <span>{t("columns.item")}</span>
                <span className="text-right">{t("columns.amount")}</span>
                <span />
              </div>
            )}
            <ol className="grid gap-2">
              {form.lines.map((line, index) => (
                <li key={index}>
                  <Row
                    open={
                      openLines.has(index) ||
                      lacking.has(`lines.${index}.net_amount`)
                    }
                    onOpenChange={toggled(setOpenLines, index)}
                    cells={
                      <>
                        <span className="text-muted-foreground tabular-nums">
                          {index + 1}.
                        </span>
                        <span className="grid min-w-0 gap-0.5">
                          <span className="line-clamp-2 font-medium">
                            {line.name.trim() ||
                              t("line", { number: index + 1 })}
                          </span>
                          <span className="text-xs text-muted-foreground tabular-nums">
                            {joined(
                              [
                                line.quantity.trim(),
                                line.unit.trim(),
                                line.unit_price.trim() &&
                                  `× ${shownAmount(line.unit_price, false)}`,
                              ]
                                .filter((part) => part)
                                .join(" "),
                              [line.vat_category, vatRate(line.vat_rate)]
                                .filter((part) => part)
                                .join(" "),
                            )}
                          </span>
                        </span>
                        <span className={ROW_AMOUNT}>
                          {line.net_amount.trim()
                            ? shownAmount(line.net_amount, false)
                            : unread}
                        </span>
                      </>
                    }
                  >
                    {/* Pairs that belong together: quantity and unit, price and amount, and
                        the category, whose names are long, beside its rate. */}
                    <div className="grid gap-3 sm:grid-cols-12">
                      <Field
                        label={t("fields.item")}
                        value={line.name}
                        onChange={setLine(index, "name")}
                        className="sm:col-span-12"
                      />
                      <Field
                        label={t("fields.quantity")}
                        value={line.quantity}
                        onChange={setLine(index, "quantity")}
                        numeric
                        className="sm:col-span-6"
                      />
                      <Field
                        label={t("fields.unit")}
                        value={line.unit}
                        onChange={setLine(index, "unit")}
                        hint={t("hints.unit")}
                        className="sm:col-span-6"
                      />
                      <Field
                        label={t("fields.unit_price")}
                        value={line.unit_price}
                        onChange={setLine(index, "unit_price")}
                        hint={t("hints.amount")}
                        numeric
                        className="sm:col-span-6"
                      />
                      <Field
                        label={t("fields.net_amount")}
                        value={line.net_amount}
                        onChange={setLine(index, "net_amount")}
                        needed={lacking.has(`lines.${index}.net_amount`)}
                        hint={t("hints.amount")}
                        numeric
                        className="sm:col-span-6"
                      />
                      <Choice
                        label={t("fields.vat_category")}
                        value={line.vat_category}
                        onChange={setLine(index, "vat_category")}
                        options={VAT_CATEGORIES.map((code) => [
                          code,
                          t(`categories.${code}`),
                        ])}
                        className="sm:col-span-8"
                      />
                      <Field
                        label={t("fields.vat_rate")}
                        value={line.vat_rate}
                        onChange={setLine(index, "vat_rate")}
                        numeric
                        className="sm:col-span-4"
                      />
                    </div>
                    <div>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="text-destructive hover:text-destructive"
                        onClick={() => {
                          setForm((was) => ({
                            ...was,
                            lines: was.lines.filter((_, at) => at !== index),
                          }));
                          setOpenLines((was) => without(was, index));
                        }}
                      >
                        <Trash2 aria-hidden="true" />
                        {t("removeLine", { number: index + 1 })}
                      </Button>
                    </div>
                  </Row>
                </li>
              ))}
            </ol>
            <div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  setOpenLines((was) => new Set(was).add(form.lines.length));
                  setForm((was) => ({
                    ...was,
                    lines: [...was.lines, emptyLine()],
                  }));
                }}
              >
                <Plus aria-hidden="true" />
                {t("addLine")}
              </Button>
            </div>
          </Panel>

          <Panel
            title={t("sections.vat")}
            summary={joined(
              ...form.vat_breakdown.map((row) =>
                [
                  row.vat_category,
                  vatRate(row.vat_rate),
                  row.tax_amount.trim() &&
                    `${t("fields.tax_amount")} ${shownAmount(row.tax_amount)}`,
                ]
                  .filter((part) => part)
                  .join(" "),
              ),
            )}
            {...panel("vat")}
          >
            {form.vat_breakdown.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("noVat")}</p>
            ) : (
              <div
                aria-hidden="true"
                className="hidden grid-cols-[1.5rem_minmax(0,1fr)_auto_1rem] gap-x-3 px-3 text-xs text-muted-foreground sm:grid"
              >
                <span />
                <span>{t("columns.category")}</span>
                <span className="text-right">{t("columns.tax")}</span>
                <span />
              </div>
            )}
            <ol className="grid gap-2">
              {form.vat_breakdown.map((row, index) => (
                <li key={index}>
                  <Row
                    open={
                      openRows.has(index) ||
                      lacking.has(`vat_breakdown.${index}.tax_amount`)
                    }
                    onOpenChange={toggled(setOpenRows, index)}
                    cells={
                      <>
                        <span className="text-muted-foreground tabular-nums">
                          {index + 1}.
                        </span>
                        <span className="grid min-w-0 gap-0.5">
                          <span className="truncate font-medium">
                            {[row.vat_category, vatRate(row.vat_rate)]
                              .filter((part) => part)
                              .join(" ")}
                          </span>
                          {row.taxable_amount.trim() ? (
                            <span className="text-xs text-muted-foreground tabular-nums">
                              {t("fields.taxable_amount")}{" "}
                              {shownAmount(row.taxable_amount, false)}
                            </span>
                          ) : null}
                        </span>
                        <span className={ROW_AMOUNT}>
                          {row.tax_amount.trim()
                            ? shownAmount(row.tax_amount, false)
                            : unread}
                        </span>
                      </>
                    }
                  >
                    <div className="grid gap-3 sm:grid-cols-12">
                      <Choice
                        label={t("fields.vat_category")}
                        value={row.vat_category}
                        onChange={setVat(index, "vat_category")}
                        options={VAT_CATEGORIES.map((code) => [
                          code,
                          t(`categories.${code}`),
                        ])}
                        className="sm:col-span-8"
                      />
                      <Field
                        label={t("fields.vat_rate")}
                        value={row.vat_rate}
                        onChange={setVat(index, "vat_rate")}
                        numeric
                        className="sm:col-span-4"
                      />
                      <Field
                        label={t("fields.taxable_amount")}
                        value={row.taxable_amount}
                        onChange={setVat(index, "taxable_amount")}
                        hint={t("hints.amount")}
                        numeric
                        className="sm:col-span-6"
                      />
                      <Field
                        label={t("fields.tax_amount")}
                        value={row.tax_amount}
                        onChange={setVat(index, "tax_amount")}
                        needed={lacking.has(
                          `vat_breakdown.${index}.tax_amount`,
                        )}
                        hint={t("hints.amount")}
                        numeric
                        className="sm:col-span-6"
                      />
                    </div>
                    <div>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="text-destructive hover:text-destructive"
                        onClick={() => {
                          setForm((was) => ({
                            ...was,
                            vat_breakdown: was.vat_breakdown.filter(
                              (_, at) => at !== index,
                            ),
                          }));
                          setOpenRows((was) => without(was, index));
                        }}
                      >
                        <Trash2 aria-hidden="true" />
                        {t("removeVat", { number: index + 1 })}
                      </Button>
                    </div>
                  </Row>
                </li>
              ))}
            </ol>
            <div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  setOpenRows((was) =>
                    new Set(was).add(form.vat_breakdown.length),
                  );
                  setForm((was) => ({
                    ...was,
                    vat_breakdown: [...was.vat_breakdown, emptyVatRow()],
                  }));
                }}
              >
                <Plus aria-hidden="true" />
                {t("addVat")}
              </Button>
            </div>
          </Panel>

          <Panel
            title={t("sections.totals")}
            summary={joined(
              form.totals.payable.trim() &&
                `${t("fields.payable")} ${shownAmount(form.totals.payable)}`,
            )}
            {...panel("totals")}
          >
            <div className="grid gap-4 sm:grid-cols-2">{totalsShown}</div>
          </Panel>

          <Panel
            title={t("sections.payment")}
            summary={joined(
              form.payment.account.trim(),
              [form.payment.model.trim(), form.payment.reference.trim()]
                .filter((part) => part)
                .join(" "),
            )}
            {...panel("payment")}
          >
            <div className="grid gap-4 sm:grid-cols-[2fr_1fr_2fr]">
              <Field
                label={t("fields.account")}
                value={form.payment.account}
                onChange={setPayment("account")}
              />
              <Field
                label={t("fields.model")}
                value={form.payment.model}
                onChange={setPayment("model")}
                numeric
              />
              <Field
                label={t("fields.reference")}
                value={form.payment.reference}
                onChange={setPayment("reference")}
              />
            </div>
          </Panel>

          {failed ? (
            <Alert variant="destructive">
              <AlertDescription>
                {failed instanceof DraftRefusedError
                  ? t("draftRefused")
                  : messageFor(failed)}
              </AlertDescription>
            </Alert>
          ) : null}
          {lacking.size > 0 ? (
            <Alert variant="destructive">
              <AlertTitle className="line-clamp-none">
                {t("requiredTitle")}
              </AlertTitle>
              <AlertDescription>
                {t("requiredList", {
                  fields: required.map(requiredLabel).join(", "),
                })}
              </AlertDescription>
            </Alert>
          ) : null}
          {refused ? (
            <Alert variant="destructive">
              <AlertTitle className="line-clamp-none">
                {t("downloadRefused")}
              </AlertTitle>
              <AlertDescription>
                <ul className="grid gap-1">
                  {refused.map((violation, index) => (
                    <li key={index}>
                      <span className="font-mono">{violation.rule_id}</span>{" "}
                      <span lang="en">{violation.message}</span>
                    </li>
                  ))}
                </ul>
              </AlertDescription>
            </Alert>
          ) : null}
          {/* The actions stay in reach while the person goes through the panels. */}
          <div className="z-10 -mx-1 mt-3 flex flex-wrap items-center gap-3 border-t bg-background/95 px-1 py-3 backdrop-blur supports-[backdrop-filter]:bg-background/80 sm:sticky sm:bottom-0">
            <Button type="submit" disabled={busy}>
              {making.isPending ? t("making") : t("make")}
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={download}
            >
              {t("download")}
            </Button>
            <Button type="button" variant="ghost" onClick={onDiscard}>
              {t("discard")}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

/** The API refused the fields themselves: a value is not in the form it asks for. */
class DraftRefusedError extends Error {}

/** The UBL the API drafts of the form's fields; a refusal of the fields is said apart. */
async function drafted(form: FieldsForm): Promise<string> {
  try {
    return await draftInvoice(fieldsOf(form));
  } catch (error) {
    if (error instanceof ApiError && error.status === 422) {
      throw new DraftRefusedError(error.message);
    }
    throw error;
  }
}

/** A choice among codes, or none: "not read". */
function Choice({
  label,
  value,
  onChange,
  options,
  needed = false,
  className,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: [string, string][];
  needed?: boolean;
  className?: string;
}) {
  const t = useTranslations("reading");
  const id = useId();
  // The select fills its column, as the fields beside it do.
  return (
    <div
      className={`grid content-start gap-1.5 [&_[data-slot=native-select-wrapper]]:w-full ${className ?? ""}`}
    >
      <Label htmlFor={id}>{label}</Label>
      <NativeSelect
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={(needed && value === "") || undefined}
      >
        <NativeSelectOption value="">{t("notRead")}</NativeSelectOption>
        {options.map(([code, name]) => (
          <NativeSelectOption key={code} value={code}>
            {name}
          </NativeSelectOption>
        ))}
      </NativeSelect>
    </div>
  );
}
