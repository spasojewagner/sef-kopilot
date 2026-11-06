"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";

import { useUploadErrorMessage } from "@/components/upload-errors";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  NativeSelect,
  NativeSelectOption,
} from "@/components/ui/native-select";
import { useRouter } from "@/i18n/navigation";
import { PROFILES, storeInvoice, type Profile } from "@/lib/invoices";
import { invoiceQuery, invoicesQuery } from "@/lib/queries";

/**
 * Sends an invoice to be validated and stored for the organization, then shows its report. The
 * report comes with the answer, so the report's page does not ask for it again.
 */
export function InvoiceUpload() {
  const t = useTranslations("upload");
  const profiles = useTranslations("profiles");
  const messageFor = useUploadErrorMessage();
  const router = useRouter();
  const client = useQueryClient();
  // Said here rather than by the browser's `required`, whose check of a file input differs
  // from one browser to another.
  const [missing, setMissing] = useState(false);
  const uploading = useMutation({
    mutationFn: ({ document, profile }: { document: File; profile: Profile }) =>
      storeInvoice(document, profile),
    onSuccess: (stored) => {
      client.setQueryData(invoiceQuery(stored.id).queryKey, stored);
      void client.invalidateQueries({ queryKey: invoicesQuery.queryKey });
      router.push(`/invoices/${stored.id}`);
    },
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fields = event.currentTarget.elements;
    const document = (fields.namedItem("invoice") as HTMLInputElement)
      .files?.[0];
    if (document === undefined || document.size === 0) {
      setMissing(true);
      return;
    }
    setMissing(false);
    const profile = (fields.namedItem("profile") as HTMLSelectElement).value;
    uploading.mutate({ document, profile: profile as Profile });
  }

  return (
    <form className="grid gap-4" onSubmit={submit}>
      <div className="grid gap-2">
        <Label htmlFor="invoice">{t("file")}</Label>
        <Input
          id="invoice"
          name="invoice"
          type="file"
          accept=".xml,application/xml,text/xml"
          aria-describedby="invoice-hint"
          aria-invalid={missing || undefined}
          onChange={() => setMissing(false)}
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
      {missing && (
        <Alert variant="destructive">
          <AlertDescription>{t("missing")}</AlertDescription>
        </Alert>
      )}
      {uploading.isError && !missing && (
        <Alert variant="destructive">
          <AlertDescription>{messageFor(uploading.error)}</AlertDescription>
        </Alert>
      )}
      <div>
        <Button type="submit" disabled={uploading.isPending}>
          {uploading.isPending ? t("pending") : t("submit")}
        </Button>
      </div>
    </form>
  );
}
