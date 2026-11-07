import type { Metadata } from "next";
import { useTranslations } from "next-intl";
import { getTranslations } from "next-intl/server";

import { InvoiceList } from "@/components/invoice-list";
import { InvoiceUpload } from "@/components/invoice-upload";
import { SignedInOnly } from "@/components/signed-in-only";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("invoices");
  return { title: t("title") };
}

/** The organization's invoices: a new one to check, and those checked before. */
export default function InvoicesPage() {
  const t = useTranslations("invoices");
  return (
    <div className="page-width grid flex-1 content-start gap-8 py-10">
      <h1 className="text-2xl font-semibold tracking-tight">{t("title")}</h1>
      <SignedInOnly>
        <Card>
          <CardHeader>
            <CardTitle>
              <h2>{t("uploadTitle")}</h2>
            </CardTitle>
            <CardDescription>{t("uploadDescription")}</CardDescription>
          </CardHeader>
          <CardContent>
            <InvoiceUpload />
          </CardContent>
        </Card>
        <section className="grid gap-4">
          <h2 className="text-lg font-semibold tracking-tight">
            {t("listTitle")}
          </h2>
          <InvoiceList />
        </section>
      </SignedInOnly>
    </div>
  );
}
