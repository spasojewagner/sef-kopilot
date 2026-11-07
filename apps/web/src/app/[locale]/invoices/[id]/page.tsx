import type { Metadata } from "next";
import { useTranslations } from "next-intl";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";

import { InvoiceReport } from "@/components/invoice-report";
import { SignedInOnly } from "@/components/signed-in-only";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("report");
  return { title: t("title") };
}

/**
 * A stored invoice's report: what the validator read from it, and every rule it fails. The
 * page around it is the same for every invoice and is built once; the id is read when the page
 * is asked for, and the report is fetched in the browser.
 */
export default function InvoiceReportPage({
  params,
}: PageProps<"/[locale]/invoices/[id]">) {
  const t = useTranslations("report");
  return (
    <div className="page-width grid flex-1 content-start gap-8 py-10">
      <SignedInOnly>
        <Suspense
          fallback={
            <p className="text-sm text-muted-foreground">{t("loading")}</p>
          }
        >
          <ReportOf params={params} />
        </Suspense>
      </SignedInOnly>
    </div>
  );
}

async function ReportOf({
  params,
}: Pick<PageProps<"/[locale]/invoices/[id]">, "params">) {
  const { id } = await params;
  return <InvoiceReport id={id} />;
}
