"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useEffect, useState, type FormEvent } from "react";

import { InvoiceReading } from "@/components/invoice-reading";
import { useReadingErrorMessage } from "@/components/reading-errors";
import { useUploadErrorMessage } from "@/components/upload-errors";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  NativeSelect,
  NativeSelectOption,
} from "@/components/ui/native-select";
import { useRouter } from "@/i18n/navigation";
import {
  documentTypeOf,
  MAX_DOCUMENT_BYTES,
  readInvoice,
  type DocumentType,
  type Extraction,
} from "@/lib/extraction";
import {
  PROFILES,
  renderingOf,
  storeInvoice,
  type Profile,
} from "@/lib/invoices";
import { SYNTHETIC_INVOICES_URL } from "@/lib/links";
import { healthQuery, invoiceQuery, invoicesQuery } from "@/lib/queries";

/**
 * Why the chosen file was not sent: there is none, it is a picture in a format that is not read,
 * or it is larger than a document may be.
 */
type Unsent = "missing" | "unreadable" | "tooLarge";

/**
 * A document read into an invoice's fields, for the visitor to check, with the address of its
 * bytes in this page, given back to the browser once it is no longer shown.
 */
type Read = {
  url: string;
  type: DocumentType;
  extraction: Extraction;
  profile: Profile;
};

/**
 * Sends an invoice to be validated and stored for the organization, then shows its report. The
 * report comes with the answer, so the report's page does not ask for it again. On a public
 * demo it first asks for a synthetic invoice (ADR-0037). A PDF or a picture of an invoice is
 * read instead (ADR-0062, beta): the API's model reads its fields, which the visitor checks
 * beside the document before the invoice is made of them.
 */
export function InvoiceUpload() {
  const t = useTranslations("upload");
  // The footer asks for the API's health on every page; the upload reads its answer, and asks
  // nothing of its own.
  const health = useQuery({ ...healthQuery, enabled: false });
  const profiles = useTranslations("profiles");
  const messageFor = useUploadErrorMessage();
  const readingMessageFor = useReadingErrorMessage();
  const router = useRouter();
  const client = useQueryClient();
  // Said here rather than by the browser's `required`, whose check of a file input differs
  // from one browser to another.
  const [unsent, setUnsent] = useState<Unsent | null>(null);
  const [read, setRead] = useState<Read | null>(null);
  const uploading = useMutation({
    mutationFn: ({ document, profile }: { document: File; profile: Profile }) =>
      storeInvoice(document, profile),
    onSuccess: (stored) => {
      client.setQueryData(invoiceQuery(stored.id).queryKey, stored);
      void client.invalidateQueries({ queryKey: invoicesQuery.queryKey });
      router.push(`/invoices/${stored.id}`);
    },
  });
  const reading = useMutation({
    mutationFn: async ({
      document,
      type,
      profile,
    }: {
      document: File;
      type: DocumentType;
      profile: Profile;
    }): Promise<Read> => {
      const extraction = await readInvoice(document, type);
      return { url: URL.createObjectURL(document), type, profile, extraction };
    },
    onSuccess: setRead,
  });
  // The document's address is given back when another is read, or the page is left.
  useEffect(() => {
    return () => {
      if (read !== null) {
        URL.revokeObjectURL(read.url);
      }
    };
  }, [read]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fields = event.currentTarget.elements;
    const document = (fields.namedItem("invoice") as HTMLInputElement)
      .files?.[0];
    if (document === undefined || document.size === 0) {
      setUnsent("missing");
      return;
    }
    const profile = (fields.namedItem("profile") as HTMLSelectElement)
      .value as Profile;
    // A PDF or a picture is read; any other file is the validator's to judge.
    if (renderingOf(document) !== null) {
      const type = documentTypeOf(document);
      if (type === null) {
        setUnsent("unreadable");
      } else if (document.size > MAX_DOCUMENT_BYTES) {
        setUnsent("tooLarge");
      } else {
        setUnsent(null);
        reading.mutate({ document, type, profile });
      }
      return;
    }
    setUnsent(null);
    uploading.mutate({ document, profile });
  }

  if (read !== null) {
    return (
      <InvoiceReading
        url={read.url}
        type={read.type}
        extraction={read.extraction}
        profile={read.profile}
        onDiscard={() => {
          setRead(null);
          reading.reset();
        }}
      />
    );
  }
  const pending = uploading.isPending || reading.isPending;

  return (
    <form className="grid gap-4" onSubmit={submit}>
      {health.data?.public_demo && (
        <Alert role="note">
          <AlertTitle className="line-clamp-none">{t("demo.title")}</AlertTitle>
          <AlertDescription>
            <p>
              {t.rich("demo.description", {
                examples: (chunks) => (
                  <a
                    href={SYNTHETIC_INVOICES_URL}
                    target="_blank"
                    rel="noreferrer"
                    className="font-medium text-foreground underline underline-offset-4"
                  >
                    {chunks}
                  </a>
                ),
              })}
            </p>
          </AlertDescription>
        </Alert>
      )}
      <div className="grid gap-2">
        <Label htmlFor="invoice">{t("file")}</Label>
        <Input
          id="invoice"
          name="invoice"
          type="file"
          accept=".xml,application/xml,text/xml,.pdf,application/pdf,.jpg,.jpeg,image/jpeg,.png,image/png,.webp,image/webp"
          // The browser's own button, drawn as the page's: a box with room to aim at.
          className="h-auto cursor-pointer border-dashed bg-muted/40 py-2.5 file:mr-4 file:h-8 file:cursor-pointer file:rounded-md file:bg-primary file:px-3 file:text-primary-foreground hover:file:bg-primary/90 dark:bg-muted/40"
          aria-describedby="invoice-hint"
          aria-invalid={unsent !== null || undefined}
          onChange={() => setUnsent(null)}
        />
        <p id="invoice-hint" className="text-sm text-muted-foreground">
          {t("fileHint")}
        </p>
      </div>
      <div className="grid gap-2">
        <Label htmlFor="profile">{t("profile")}</Label>
        <NativeSelect id="profile" name="profile" defaultValue="srb">
          {PROFILES.map((profile) => (
            <NativeSelectOption key={profile} value={profile}>
              {profiles(profile)}
            </NativeSelectOption>
          ))}
        </NativeSelect>
      </div>
      {unsent !== null && (
        <Alert variant="destructive">
          <AlertDescription>{t(unsent)}</AlertDescription>
        </Alert>
      )}
      {uploading.isError && unsent === null && (
        <Alert variant="destructive">
          <AlertDescription>{messageFor(uploading.error)}</AlertDescription>
        </Alert>
      )}
      {reading.isError && unsent === null && (
        <Alert variant="destructive">
          <AlertDescription>
            {readingMessageFor(reading.error)}
          </AlertDescription>
        </Alert>
      )}
      <div>
        <Button type="submit" disabled={pending}>
          {reading.isPending
            ? t("reading")
            : uploading.isPending
              ? t("pending")
              : t("submit")}
        </Button>
      </div>
    </form>
  );
}
