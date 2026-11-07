import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { AuthFrame } from "@/components/auth-frame";
import { RegisterForm } from "@/components/register-form";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("register");
  return { title: t("title") };
}

export default function RegisterPage() {
  return (
    <AuthFrame>
      <RegisterForm />
    </AuthFrame>
  );
}
