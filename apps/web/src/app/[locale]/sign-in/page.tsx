import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { AuthFrame } from "@/components/auth-frame";
import { SignInForm } from "@/components/sign-in-form";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("signIn");
  return { title: t("title") };
}

export default function SignInPage() {
  return (
    <AuthFrame>
      <SignInForm />
    </AuthFrame>
  );
}
