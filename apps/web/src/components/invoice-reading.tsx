"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FileText } from "lucide-react";
import { useTranslations } from "next-intl";
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
import {
  draftFileName,
  draftInvoice,
  emptyLine,
  emptyVatRow,
  fieldsOf,
  formOf,
  missingIn,
  TYPE_CODES,
  VAT_CATEGORIES,
  type DocumentType,
  type Extraction,
  type FieldsForm,
  type LineForm,
  type Needed,
  type PartyForm,
  type TotalsForm,
  type VatForm,
} from "@/lib/extraction";
import { storeInvoice, type Profile } from "@/lib/invoices";
import { invoiceQuery, invoicesQuery } from "@/lib/queries";

/** The label of each field SEF needs, and the party it belongs to, if any. */
const NEEDED_LABEL: Record<
  Exclude<Needed, "lines">,
  [
    "number" | "issue_date" | "currency" | "name" | "tax_id" | "payable",
    "seller" | "buyer" | null,
  ]
> = {
  number: ["number", null],
  issue_date: ["issue_date", null],
  currency: ["currency", null],
  "seller.name": ["name", "seller"],
  "seller.tax_id": ["tax_id", "seller"],
  "buyer.name": ["name", "buyer"],
  "buyer.tax_id": ["tax_id", "buyer"],
  "totals.payable": ["payable", null],
};

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

/** A group of fields under a heading of its own. */
function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset className="grid gap-4 border-t pt-5 first:border-t-0 first:pt-0">
      <legend className="float-left mb-1 w-full text-base font-semibold tracking-tight">
        {title}
      </legend>
      {children}
    </fieldset>
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
          className="h-[70vh] w-full rounded-md border bg-muted/40"
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
 * shows its report; or the drafted XML is downloaded. Nothing is kept until then.
 */
export function InvoiceReading({
  url,
  type,
  extraction,
  profile,
  onDiscard,
}: {
  url: string;
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

  const making = useMutation({
    mutationFn: async () =>
      storeInvoice(
        new Blob([await drafted(form)], { type: "application/xml" }),
        profile,
      ),
    onSuccess: (stored) => {
      client.setQueryData(invoiceQuery(stored.id).queryKey, stored);
      void client.invalidateQueries({ queryKey: invoicesQuery.queryKey });
      router.push(`/invoices/${stored.id}`);
    },
  });
  const downloading = useMutation({
    mutationFn: () => drafted(form),
    onSuccess: (xml) => {
      const url = URL.createObjectURL(
        new Blob([xml], { type: "application/xml" }),
      );
      const link = window.document.createElement("a");
      link.href = url;
      link.download = draftFileName(form);
      link.click();
      URL.revokeObjectURL(url);
    },
  });
  const failed = making.error ?? downloading.error;
  const busy = making.isPending || downloading.isPending;

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

  function party(which: "seller" | "buyer") {
    const values = form[which];
    const needed = (key: keyof PartyForm) =>
      needs.has(`${which}.${key}` as Needed);
    return (
      <Group title={t(`sections.${which}`)}>
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
      </Group>
    );
  }

  return (
    <div className="grid gap-6">
      <div className="grid gap-2">
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
      </div>
      <Alert role="note">
        <AlertDescription>{t("check")}</AlertDescription>
      </Alert>
      <div className="grid items-start gap-8 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <section aria-label={t("document")} className="lg:sticky lg:top-24">
          <DocumentShown url={url} type={type} />
        </section>
        <form
          className="grid gap-6"
          onSubmit={(event) => {
            event.preventDefault();
            making.mutate();
          }}
        >
          {missing.length > 0 ? (
            <Alert role="status">
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
          ) : null}

          <Group title={t("sections.invoice")}>
            <div className="grid gap-4 sm:grid-cols-2">
              <Choice
                label={t("fields.type_code")}
                value={form.type_code}
                onChange={set("type_code")}
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
          </Group>

          {party("seller")}
          {party("buyer")}

          <Group title={t("sections.lines")}>
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
            ) : null}
            <ol className="grid gap-4">
              {form.lines.map((line, index) => (
                <li
                  key={index}
                  className="grid gap-3 rounded-lg border bg-muted/20 p-4"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium">
                      {t("line", { number: index + 1 })}
                    </span>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() =>
                        setForm((was) => ({
                          ...was,
                          lines: was.lines.filter((_, at) => at !== index),
                        }))
                      }
                    >
                      {t("removeLine", { number: index + 1 })}
                    </Button>
                  </div>
                  {/* Pairs that belong together: quantity and unit, price and amount, and the
                      category, whose names are long, beside its rate. */}
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
                </li>
              ))}
            </ol>
            <div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() =>
                  setForm((was) => ({
                    ...was,
                    lines: [...was.lines, emptyLine()],
                  }))
                }
              >
                {t("addLine")}
              </Button>
            </div>
          </Group>

          <Group title={t("sections.vat")}>
            {form.vat_breakdown.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("noVat")}</p>
            ) : null}
            <ol className="grid gap-4">
              {form.vat_breakdown.map((row, index) => (
                <li
                  key={index}
                  className="grid gap-3 rounded-lg border bg-muted/20 p-4"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium">
                      {t("vatRow", { number: index + 1 })}
                    </span>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() =>
                        setForm((was) => ({
                          ...was,
                          vat_breakdown: was.vat_breakdown.filter(
                            (_, at) => at !== index,
                          ),
                        }))
                      }
                    >
                      {t("removeVat", { number: index + 1 })}
                    </Button>
                  </div>
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
                      hint={t("hints.amount")}
                      numeric
                      className="sm:col-span-6"
                    />
                  </div>
                </li>
              ))}
            </ol>
            <div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() =>
                  setForm((was) => ({
                    ...was,
                    vat_breakdown: [...was.vat_breakdown, emptyVatRow()],
                  }))
                }
              >
                {t("addVat")}
              </Button>
            </div>
          </Group>

          <Group title={t("sections.totals")}>
            <div className="grid gap-4 sm:grid-cols-2">
              {(
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
                  needed={key === "payable" && needs.has("totals.payable")}
                  hint={t("hints.amount")}
                  numeric
                />
              ))}
            </div>
          </Group>

          <Group title={t("sections.payment")}>
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
          </Group>

          {failed ? (
            <Alert variant="destructive">
              <AlertDescription>
                {failed instanceof DraftRefusedError
                  ? t("draftRefused")
                  : messageFor(failed)}
              </AlertDescription>
            </Alert>
          ) : null}
          <div className="flex flex-wrap gap-3">
            <Button type="submit" disabled={busy}>
              {making.isPending ? t("making") : t("make")}
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={() => downloading.mutate()}
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
  className,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: [string, string][];
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
