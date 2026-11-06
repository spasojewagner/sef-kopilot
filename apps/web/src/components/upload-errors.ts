"use client";

import { useTranslations } from "next-intl";

import { ApiError } from "@/lib/api";

/** Why an invoice was not stored, in the visitor's language. */
export function useUploadErrorMessage(): (error: unknown) => string {
  const t = useTranslations("uploadErrors");
  return (error) => {
    if (!(error instanceof ApiError)) {
      return t("unreachable");
    }
    const seconds = error.retryAfter;
    switch (error.status) {
      case 401:
        return t("signedOut");
      case 403:
        return t("forbidden");
      case 408:
        return t("tooSlow");
      case 413:
        return t("tooLarge");
      case 415:
        return t("notXml");
      case 422:
        return t("notValidated");
      case 429:
        return t("tooMany", { seconds: seconds ?? 60 });
      case 503:
        return seconds === null
          ? t("validatorAway")
          : t("validatorBusy", { seconds });
      case 507:
        return t("storageFull");
      default:
        return t("failed");
    }
  };
}
