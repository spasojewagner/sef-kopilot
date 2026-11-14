"use client";

import { useTranslations } from "next-intl";

import { ApiError } from "@/lib/api";

/**
 * What went wrong with a sign-in or a registration, in the visitor's language. The API's own
 * reasons are English and for developers; the visitor reads these.
 */
export function useAuthErrorMessage(): (error: unknown) => string {
  const t = useTranslations("authErrors");
  return (error) => {
    if (!(error instanceof ApiError)) {
      // The browser could not reach the API, was not allowed to read it, or gave up.
      return t("unreachable");
    }
    switch (error.status) {
      case 401:
        return t("wrongCredentials");
      case 403:
        return t("notAMember");
      case 409:
        return t("emailTaken");
      case 422:
        return commonPassword(error) ? t("commonPassword") : t("invalid");
      case 429:
        return t("tooMany", { seconds: error.retryAfter ?? 60 });
      default:
        return t("failed");
    }
  };
}

/** Whether the API refused a new password as among the most common ones. */
function commonPassword(error: ApiError): boolean {
  const detail = (error.body as { detail?: unknown } | null)?.detail;
  return (
    Array.isArray(detail) &&
    detail.some(
      (each) =>
        typeof each === "object" &&
        each !== null &&
        (each as { type?: unknown }).type === "common_password",
    )
  );
}
