"use client";

import { useTranslations } from "next-intl";

import { ApiError } from "@/lib/api";

/** Why a PDF or a picture was not read into an invoice's fields, in the visitor's language. */
export function useReadingErrorMessage(): (error: unknown) => string {
  const t = useTranslations("readingErrors");
  return (error) => {
    if (!(error instanceof ApiError)) {
      return t("unreachable");
    }
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
        return t("notDocument");
      case 422:
        return t("unreadable");
      case 429:
        return t("tooMany", { seconds: error.retryAfter ?? 60 });
      case 502:
        return t("modelAway");
      case 503:
        return t("noModel");
      case 504:
        return t("modelSlow");
      default:
        return t("failed");
    }
  };
}
