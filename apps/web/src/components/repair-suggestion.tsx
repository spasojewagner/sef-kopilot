"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Link, useRouter } from "@/i18n/navigation";
import { ApiError } from "@/lib/api";
import { languageOf } from "@/lib/explanations";
import { repairQuery, repairsQuery } from "@/lib/queries";
import { conflictOf, suggestRepair } from "@/lib/repairs";

/**
 * Asks the language model for a repair of the stored invoice ``invoiceId``, its reasons in the
 * page's language, and opens the repair it writes. Each request spends the model's requests,
 * so nothing is asked until the visitor asks, and a failure waits for them to try again.
 */
export function RepairSuggestion({ invoiceId }: { invoiceId: string }) {
  const t = useTranslations("suggestion");
  const language = languageOf(useLocale());
  const client = useQueryClient();
  const router = useRouter();
  const why = useSuggestionErrorMessage();
  const suggesting = useMutation({
    mutationFn: () => suggestRepair(invoiceId, language),
    onSuccess: (repair) => {
      // Its page shows it at once, and the invoice's list asks for it.
      client.setQueryData(repairQuery(invoiceId, repair.id).queryKey, repair);
      void client.invalidateQueries({
        queryKey: repairsQuery(invoiceId).queryKey,
      });
    },
  });
  const ask = () =>
    suggesting.mutate(undefined, {
      // Called only while this page is shown: a visitor who has gone elsewhere stays there.
      onSuccess: (repair) =>
        router.push(`/invoices/${invoiceId}/repairs/${repair.id}`),
    });

  if (suggesting.isPending) {
    return (
      <p role="status" className="text-sm text-muted-foreground">
        {t("writing")}
      </p>
    );
  }
  if (suggesting.isSuccess) {
    return (
      <p role="status" className="text-sm">
        {t("written")}{" "}
        <Link
          href={`/invoices/${invoiceId}/repairs/${suggesting.data.id}`}
          className="underline underline-offset-4"
        >
          {t("open")}
        </Link>
      </p>
    );
  }
  if (suggesting.isError) {
    const { message, again } = why(suggesting.error);
    return (
      <Alert variant="destructive">
        <AlertDescription className="grid gap-3">
          <p>{message}</p>
          {again && (
            <div>
              <Button variant="outline" size="sm" onClick={ask}>
                {t("again")}
              </Button>
            </div>
          )}
        </AlertDescription>
      </Alert>
    );
  }
  return (
    <div className="grid gap-3 rounded-lg border p-4 text-sm">
      <p>{t("intro")}</p>
      <p className="text-muted-foreground">{t("privacy")}</p>
      <div>
        <Button onClick={ask}>{t("ask")}</Button>
      </div>
    </div>
  );
}

/**
 * Why no repair was suggested, in the visitor's language, and whether asking again could help:
 * not while the invoice is valid, its repairs wait for decisions, it is gone, or the server
 * has no model or no validator.
 */
function useSuggestionErrorMessage(): (error: unknown) => {
  message: string;
  again: boolean;
} {
  const t = useTranslations("suggestion.errors");
  return (error) => {
    // The browser's DOMException, which need not be an Error of this realm.
    const name =
      typeof error === "object" && error !== null && "name" in error
        ? error.name
        : null;
    if (name === "TimeoutError") {
      return { message: t("tooSlow"), again: true };
    }
    if (!(error instanceof ApiError)) {
      return { message: t("unreachable"), again: true };
    }
    switch (conflictOf(error)) {
      case "nothing-to-repair":
        return { message: t("nothingToRepair"), again: false };
      case "too-many-waiting":
        return { message: t("tooManyWaiting"), again: false };
      case "invoice-changed":
        return { message: t("invoiceChanged"), again: true };
    }
    const seconds = error.retryAfter;
    switch (error.status) {
      case 404:
        return { message: t("notFound"), again: false };
      case 422:
        return { message: t("noPatch"), again: true };
      case 429:
        return {
          message: t("tooMany", { seconds: seconds ?? 60 }),
          again: true,
        };
      case 502:
        return { message: t("modelFailed"), again: true };
      case 503:
        // Without `Retry-After` the server has no model, or no validator: asking again now
        // would not give it one.
        return seconds === null
          ? { message: t("unavailable"), again: false }
          : { message: t("busy", { seconds }), again: true };
      case 504:
        return { message: t("tooSlow"), again: true };
      default:
        return { message: t("failed"), again: true };
    }
  };
}
