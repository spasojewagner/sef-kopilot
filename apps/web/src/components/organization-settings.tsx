"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useSession } from "@/hooks/use-session";
import type { Organization } from "@/lib/organization";
import { meQuery, organizationQuery } from "@/lib/queries";
import type { Identity } from "@/lib/session";

/**
 * The visitor's organization: its name, who the visitor is in it, and how long it keeps its
 * stored invoices (ADR-0039).
 */
export function OrganizationSettings() {
  const t = useTranslations("organization");
  const organization = useQuery(organizationQuery);
  const identity = useIdentity();

  if (organization.isPending) {
    return (
      <p role="status" className="text-sm text-muted-foreground">
        {t("loading")}
      </p>
    );
  }
  if (organization.isError) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{t("notLoaded")}</AlertDescription>
      </Alert>
    );
  }
  return (
    <div className="grid gap-8">
      <Who organization={organization.data} identity={identity} />
      <Retention
        organization={organization.data}
        owner={identity?.role === "owner"}
      />
    </div>
  );
}

/**
 * Who the visitor is, with the role the API says they hold now, or the one they held when they
 * signed in until it has said: a role changed since is the API's to enforce, and the page
 * follows it once it knows.
 */
function useIdentity(): Identity | null {
  const session = useSession();
  const me = useQuery({ ...meQuery, enabled: session.status === "signed-in" });
  return session.status === "signed-in" ? (me.data ?? session.identity) : null;
}

function Who({
  organization,
  identity,
}: {
  organization: Organization;
  identity: Identity | null;
}) {
  const t = useTranslations("organization");
  return (
    <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[max-content_1fr]">
      <dt className="text-muted-foreground">{t("name")}</dt>
      <dd className="font-medium">{organization.name}</dd>
      {identity !== null && (
        <>
          <dt className="text-muted-foreground">{t("you")}</dt>
          <dd className="break-all">{identity.user.email}</dd>
          <dt className="text-muted-foreground">{t("role")}</dt>
          <dd>{t(`roles.${identity.role}`)}</dd>
        </>
      )}
    </dl>
  );
}

/** A period of ``days``, in years when it is a whole number of them. */
function usePeriod(): (days: number) => string {
  const t = useTranslations("organization.retention");
  return (days) =>
    days % 365 === 0 ? t("years", { years: days / 365 }) : t("days", { days });
}

function Retention({
  organization,
  owner,
}: {
  organization: Organization;
  owner: boolean;
}) {
  const t = useTranslations("organization.retention");
  const period = usePeriod();
  const days = organization.invoice_retention_days;
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
          {days === null ? t("none") : t("period", { period: period(days) })}
        </p>
        {!owner && <p className="text-muted-foreground">{t("ownersOnly")}</p>}
      </CardContent>
    </Card>
  );
}
