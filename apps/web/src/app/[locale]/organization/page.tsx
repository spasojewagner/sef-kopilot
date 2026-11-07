import type { Metadata } from "next";
import { useTranslations } from "next-intl";
import { getTranslations } from "next-intl/server";

import { OrganizationSettings } from "@/components/organization-settings";
import { SignedInOnly } from "@/components/signed-in-only";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("organization");
  return { title: t("title") };
}

/** The visitor's organization, and how long it keeps its stored invoices. */
export default function OrganizationPage() {
  const t = useTranslations("organization");
  return (
    <main className="mx-auto grid w-full max-w-5xl flex-1 content-start gap-8 px-6 py-10">
      <h1 className="text-2xl font-semibold tracking-tight">{t("title")}</h1>
      <SignedInOnly>
        <OrganizationSettings />
      </SignedInOnly>
    </main>
  );
}
