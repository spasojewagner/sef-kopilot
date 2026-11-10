/**
 * Invoices read from a PDF or a picture (ADR-0062, beta). The API's reading model reads a
 * document's fields; the visitor checks them against the document and corrects them; the API
 * then drafts the UBL invoice of them, in code, and the invoice is stored and validated as any
 * other. Every call is in the visitor's name.
 */
import type { Schemas } from "@/lib/api";
import { authorized } from "@/lib/session";

export type InvoiceFields = Schemas["InvoiceFields"];
export type Extraction = Schemas["Extraction"];

/**
 * A reading may take longer than an upload: the API reads the document for 30 s at most, the
 * model it for 90 s, and an instance on a free tier may first have to wake up.
 */
export const READING_TIMEOUT_MS = 150_000;
/** The largest document the API reads, as its settings say by default: 10 MiB. */
export const MAX_DOCUMENT_BYTES = 10 * 1024 * 1024;

/** The media types the API reads an invoice from. */
export const DOCUMENT_TYPES = [
  "application/pdf",
  "image/jpeg",
  "image/png",
  "image/webp",
] as const;
export type DocumentType = (typeof DOCUMENT_TYPES)[number];

const BY_NAME: [RegExp, DocumentType][] = [
  [/\.pdf$/i, "application/pdf"],
  [/\.jpe?g$/i, "image/jpeg"],
  [/\.png$/i, "image/png"],
  [/\.webp$/i, "image/webp"],
];

/**
 * The media type a document is read as: the browser's when it is one the API reads, or else
 * the one its name says; null for any other, a HEIC photograph or a GIF say.
 */
export function documentTypeOf(file: File): DocumentType | null {
  const given = DOCUMENT_TYPES.find((type) => type === file.type);
  if (given !== undefined) {
    return given;
  }
  return BY_NAME.find(([name]) => name.test(file.name))?.[1] ?? null;
}

/** Has the API's reading model read the fields of the invoice ``document`` shows. */
export function readInvoice(
  document: Blob,
  type: DocumentType,
): Promise<Extraction> {
  return authorized<Extraction>("/invoices/extract", {
    method: "POST",
    headers: { "Content-Type": type },
    body: document,
    timeoutMs: READING_TIMEOUT_MS,
  });
}

/** The UBL invoice the API drafts of ``fields``, as XML. */
export function draftInvoice(fields: InvoiceFields): Promise<string> {
  return authorized<string>("/invoices/draft", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/xml",
    },
    body: JSON.stringify(fields),
    text: true,
  });
}

// --- the fields as a form holds them --------------------------------------------------------

/** A party as the form holds it: every value text, empty where nothing was read. */
export type PartyForm = {
  name: string;
  tax_id: string;
  company_id: string;
  street: string;
  city: string;
  postal_code: string;
  country: string;
  email: string;
};
export type LineForm = {
  name: string;
  quantity: string;
  unit: string;
  unit_price: string;
  net_amount: string;
  vat_category: string;
  vat_rate: string;
};
export type VatForm = {
  vat_category: string;
  vat_rate: string;
  taxable_amount: string;
  tax_amount: string;
};
export type TotalsForm = {
  line_total: string;
  tax_exclusive: string;
  tax: string;
  tax_inclusive: string;
  prepaid: string;
  payable: string;
};
export type PaymentForm = { account: string; model: string; reference: string };
/** The fields as the form holds them, with the seller's VAT register as yes, no or unknown. */
export type FieldsForm = {
  type_code: string;
  number: string;
  issue_date: string;
  due_date: string;
  delivery_date: string;
  currency: string;
  buyer_reference: string;
  seller: PartyForm;
  seller_in_vat_register: "" | "yes" | "no";
  buyer: PartyForm;
  lines: LineForm[];
  vat_breakdown: VatForm[];
  totals: TotalsForm;
  payment: PaymentForm;
};

/** The codes of the documents a reading tells apart, invoice first. */
export const TYPE_CODES = ["380", "386", "381", "383"] as const;
/** The VAT categories SRB-CIUS allows, the charged ones first. */
export const VAT_CATEGORIES = [
  "S",
  "AE",
  "Z",
  "E",
  "R",
  "O",
  "OE",
  "SS",
  "N",
] as const;

const PARTY: (keyof PartyForm)[] = [
  "name",
  "tax_id",
  "company_id",
  "street",
  "city",
  "postal_code",
  "country",
  "email",
];
const LINE: (keyof LineForm)[] = [
  "name",
  "quantity",
  "unit",
  "unit_price",
  "net_amount",
  "vat_category",
  "vat_rate",
];
const VAT: (keyof VatForm)[] = [
  "vat_category",
  "vat_rate",
  "taxable_amount",
  "tax_amount",
];
const TOTALS: (keyof TotalsForm)[] = [
  "line_total",
  "tax_exclusive",
  "tax",
  "tax_inclusive",
  "prepaid",
  "payable",
];
const PAYMENT: (keyof PaymentForm)[] = ["account", "model", "reference"];

function texts<K extends string>(
  keys: K[],
  read: Partial<Record<K, unknown>> | null | undefined,
): Record<K, string> {
  return Object.fromEntries(
    keys.map((key) => [key, read?.[key] == null ? "" : String(read[key])]),
  ) as Record<K, string>;
}

function values<K extends string>(
  keys: K[],
  form: Record<K, string>,
): Record<K, string | null> {
  return Object.fromEntries(
    keys.map((key) => [key, form[key].trim() === "" ? null : form[key].trim()]),
  ) as Record<K, string | null>;
}

/** An empty line, for one the reading missed. */
export function emptyLine(): LineForm {
  return texts(LINE, null);
}

/** An empty row of the VAT recapitulation. */
export function emptyVatRow(): VatForm {
  return texts(VAT, null);
}

/** The fields read, as the form holds them. */
export function formOf(fields: InvoiceFields): FieldsForm {
  const registered = fields.seller_in_vat_register;
  return {
    ...texts(
      [
        "type_code",
        "number",
        "issue_date",
        "due_date",
        "delivery_date",
        "currency",
        "buyer_reference",
      ],
      fields,
    ),
    seller: texts(PARTY, fields.seller),
    seller_in_vat_register: registered == null ? "" : registered ? "yes" : "no",
    buyer: texts(PARTY, fields.buyer),
    lines: (fields.lines ?? []).map((line) => texts(LINE, line)),
    vat_breakdown: (fields.vat_breakdown ?? []).map((row) => texts(VAT, row)),
    totals: texts(TOTALS, fields.totals),
    payment: texts(PAYMENT, fields.payment),
  };
}

/** The form's fields as the API takes them: an empty value is one not given. */
export function fieldsOf(form: FieldsForm): InvoiceFields {
  const plain = values(
    [
      "type_code",
      "number",
      "issue_date",
      "due_date",
      "delivery_date",
      "currency",
      "buyer_reference",
    ],
    form,
  );
  return {
    ...plain,
    type_code: plain.type_code as InvoiceFields["type_code"],
    seller: values(PARTY, form.seller),
    seller_in_vat_register:
      form.seller_in_vat_register === ""
        ? null
        : form.seller_in_vat_register === "yes",
    buyer: values(PARTY, form.buyer),
    lines: form.lines.map((line) => {
      const read = values(LINE, line);
      return {
        ...read,
        vat_category: read.vat_category as Schemas["Line"]["vat_category"],
      };
    }),
    vat_breakdown: form.vat_breakdown.map((row) => {
      const read = values(VAT, row);
      return {
        ...read,
        vat_category:
          read.vat_category as Schemas["VatSubtotal"]["vat_category"],
      };
    }),
    totals: values(TOTALS, form.totals),
    payment: values(PAYMENT, form.payment),
  };
}

/** The fields SEF cannot do without, by the name the form gives them. */
export type Needed =
  | "number"
  | "issue_date"
  | "currency"
  | "seller.name"
  | "seller.tax_id"
  | "buyer.name"
  | "buyer.tax_id"
  | "lines"
  | "totals.payable";

/**
 * The fields SEF needs that are empty: what the reading did not find, for the visitor to fill
 * in before the invoice is made. The validator judges the rest.
 */
export function missingIn(form: FieldsForm): Needed[] {
  const empty = (value: string) => value.trim() === "";
  const missing: [Needed, boolean][] = [
    ["number", empty(form.number)],
    ["issue_date", empty(form.issue_date)],
    ["currency", empty(form.currency)],
    ["seller.name", empty(form.seller.name)],
    ["seller.tax_id", empty(form.seller.tax_id)],
    ["buyer.name", empty(form.buyer.name)],
    ["buyer.tax_id", empty(form.buyer.tax_id)],
    ["lines", form.lines.length === 0],
    ["totals.payable", empty(form.totals.payable)],
  ];
  return missing.filter(([, isMissing]) => isMissing).map(([name]) => name);
}

/** The name of the file the drafted invoice is saved as: its number, made safe for a file. */
export function draftFileName(form: FieldsForm): string {
  const number = form.number.trim().replace(/[^\p{L}\p{N}._-]+/gu, "-");
  return `${number || "faktura"}.xml`;
}
