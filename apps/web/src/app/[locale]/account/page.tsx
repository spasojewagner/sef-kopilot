import type { Metadata } from "next";
import { useTranslations } from "next-intl";
import { getTranslations } from "next-intl/server";

import { PasswordChangeForm } from "@/components/password-change-form";
import { SignedInOnly } from "@/components/signed-in-only";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("passwordChange");
  return { title: t("title") };
}

export default function AccountPage() {
  const t = useTranslations("passwordChange");
  return (
    <div className="page-width grid flex-1 content-start gap-8 py-10">
      <h1 className="text-2xl font-semibold tracking-tight">{t("title")}</h1>
      <SignedInOnly>
        <PasswordChangeForm />
      </SignedInOnly>
    </div>
  );
}
