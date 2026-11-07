import type { Metadata } from "next";
import { useTranslations } from "next-intl";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";

import { AppConsent } from "@/components/app-consent";
import { AuthFrame } from "@/components/auth-frame";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("consent");
  return { title: t("pageTitle"), robots: { index: false, follow: false } };
}

/**
 * Where the API's authorization server sends a person whom an MCP client asks to act for,
 * `?request=…` (ADR-0044). The page around the request is the same for every one and is built
 * once; the request's id is read when the page is asked for, and the request is fetched in the
 * browser, in the visitor's name.
 */
export default function ConsentPage({
  searchParams,
}: PageProps<"/[locale]/oauth/consent">) {
  const t = useTranslations("consent");
  return (
    <AuthFrame>
      <Suspense
        fallback={
          <p className="text-sm text-muted-foreground">{t("loading")}</p>
        }
      >
        <ConsentFor searchParams={searchParams} />
      </Suspense>
    </AuthFrame>
  );
}

async function ConsentFor({
  searchParams,
}: Pick<PageProps<"/[locale]/oauth/consent">, "searchParams">) {
  const { request } = await searchParams;
  const id = typeof request === "string" && request !== "" ? request : null;
  return <AppConsent requestId={id} />;
}
