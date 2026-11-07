import type { Metadata } from "next";
import { useTranslations } from "next-intl";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";

import { RepairView } from "@/components/repair-view";
import { SignedInOnly } from "@/components/signed-in-only";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("repair");
  return { title: t("title") };
}

/**
 * A repair of a stored invoice: its patches, the difference they make, and the report on what
 * they leave. Built once, as the invoice's report is; the ids are read when it is asked for.
 */
export default function RepairPage({
  params,
}: PageProps<"/[locale]/invoices/[id]/repairs/[repairId]">) {
  const t = useTranslations("repair");
  return (
    <div className="page-width grid flex-1 content-start gap-8 py-10">
      <SignedInOnly>
        <Suspense
          fallback={
            <p className="text-sm text-muted-foreground">{t("loading")}</p>
          }
        >
          <RepairOf params={params} />
        </Suspense>
      </SignedInOnly>
    </div>
  );
}

async function RepairOf({
  params,
}: Pick<PageProps<"/[locale]/invoices/[id]/repairs/[repairId]">, "params">) {
  const { id, repairId } = await params;
  return <RepairView invoiceId={id} repairId={repairId} />;
}
