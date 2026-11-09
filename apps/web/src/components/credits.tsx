"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import { useSyncExternalStore } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ApiError } from "@/lib/api";
import {
  type Billing,
  type CreditEntry,
  formatPrice,
  openCheckout,
  type Returned,
  returnedFrom,
} from "@/lib/billing";
import { formatMoment } from "@/lib/format";
import { billingQuery, creditEntriesQuery, meQuery } from "@/lib/queries";

/** How often, and how many times, the credits are read again after a payment. */
export const CONFIRMING_EVERY_MS = 5_000;
const CONFIRMING_READS = 12;

/**
 * The organization's credits, where the server's billing is on (ADR-0059): how many it holds,
 * which every member who stores invoices sees; and, for an owner, the packs on sale, each
 * bought on Stripe's page in its sandbox (ADR-0060), and the latest changes of the ledger.
 * Where billing is off, storing costs nothing and the card is not shown.
 */
export function Credits({ owner }: { owner: boolean }) {
  const returned = useReturned();
  // Back from paying, the credits are read again for a minute: Stripe tells the API a moment
  // after it tells the visitor.
  const billing = useQuery({
    ...billingQuery,
    refetchInterval: (query) =>
      returned === "paid" && query.state.dataUpdateCount < CONFIRMING_READS
        ? CONFIRMING_EVERY_MS
        : false,
  });
  if (!billing.isSuccess || !billing.data.enabled) {
    return null;
  }
  return (
    <CreditsCard billing={billing.data} owner={owner} returned={returned} />
  );
}

function CreditsCard({
  billing,
  owner,
  returned,
}: {
  billing: Billing;
  owner: boolean;
  returned: Returned;
}) {
  const t = useTranslations("organization.credits");
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>{t("title")}</h2>
        </CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 text-sm">
        <p>
          {t("balance", {
            balance: billing.balance ?? 0,
            perInvoice: billing.per_invoice ?? 1,
          })}
        </p>
        {returned === "paid" && <p role="status">{t("paid")}</p>}
        {returned === "cancelled" && (
          <p role="status" className="text-muted-foreground">
            {t("cancelled")}
          </p>
        )}
        {owner ? (
          <>
            <Packs billing={billing} />
            <Ledger />
          </>
        ) : (
          <p className="text-muted-foreground">{t("ownersBuy")}</p>
        )}
      </CardContent>
    </Card>
  );
}

/** The packs on sale, each a button that opens Stripe's page for it. */
function Packs({ billing }: { billing: Billing }) {
  const t = useTranslations("organization.credits");
  const locale = useLocale();
  const why = useCheckoutErrorMessage();
  const client = useQueryClient();
  const buying = useMutation({
    mutationFn: openCheckout,
    onSuccess: (url) => window.location.assign(url),
    onError: (error) => {
      if (error instanceof ApiError && error.status === 403) {
        void client.invalidateQueries({ queryKey: meQuery.queryKey });
      }
    },
  });
  if (billing.packs.length === 0) {
    return <p className="text-muted-foreground">{t("notSold")}</p>;
  }
  return (
    <div className="grid gap-3">
      <p>{t("buy")}</p>
      <div className="flex flex-wrap gap-2">
        {billing.packs.map((pack) => (
          <Button
            key={pack.credits}
            type="button"
            variant="outline"
            disabled={buying.isPending}
            onClick={() => buying.mutate(pack.credits)}
          >
            {t("pack", {
              credits: pack.credits,
              price: formatPrice(locale, pack),
            })}
          </Button>
        ))}
      </div>
      <p className="text-muted-foreground">{t("sandbox")}</p>
      {buying.isPending && (
        <p role="status" className="text-muted-foreground">
          {t("opening")}
        </p>
      )}
      {buying.isError && (
        <Alert variant="destructive">
          <AlertDescription>{why(buying.error)}</AlertDescription>
        </Alert>
      )}
    </div>
  );
}

/** The latest changes of the organization's credits, newest first. */
function Ledger() {
  const t = useTranslations("organization.credits");
  const locale = useLocale();
  const entries = useQuery(creditEntriesQuery);
  if (entries.isPending) {
    return (
      <p role="status" className="text-muted-foreground">
        {t("loading")}
      </p>
    );
  }
  if (entries.isError) {
    return <p className="text-muted-foreground">{t("notLoaded")}</p>;
  }
  if (entries.data.length === 0) {
    return <p className="text-muted-foreground">{t("noEntries")}</p>;
  }
  return (
    <Table>
      <caption className="sr-only">{t("ledger")}</caption>
      <TableHeader>
        <TableRow>
          <TableHead>{t("when")}</TableHead>
          <TableHead>{t("what")}</TableHead>
          <TableHead className="text-right">{t("change")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {entries.data.map((entry: CreditEntry) => (
          <TableRow key={entry.id}>
            <TableCell>{formatMoment(locale, entry.at)}</TableCell>
            <TableCell>{t(`kinds.${entry.kind}`)}</TableCell>
            <TableCell className="text-right tabular-nums">
              {entry.delta > 0 ? `+${entry.delta}` : entry.delta}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/** What the visitor came back from Stripe with, read from the address once the page runs in
 * the browser (nothing on the server). */
function useReturned(): Returned {
  const search = useSyncExternalStore(
    subscribeToNothing,
    () => window.location.search,
    () => "",
  );
  return returnedFrom(search);
}

/** The address's query does not change while the page is open: nothing to listen to. */
function subscribeToNothing(): () => void {
  return () => {};
}

/** Why the checkout did not open, in the visitor's language. */
function useCheckoutErrorMessage(): (error: unknown) => string {
  const t = useTranslations("organization.credits.errors");
  return (error) => {
    if (!(error instanceof ApiError)) {
      return t("unreachable");
    }
    switch (error.status) {
      case 401:
        return t("signedOut");
      case 403:
        return t("forbidden");
      case 502:
        return t("stripe");
      case 503:
        return t("notSold");
      default:
        return t("failed");
    }
  };
}
