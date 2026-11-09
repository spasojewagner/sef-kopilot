"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
} from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { ApiKeys } from "@/components/api-keys";
import { Credits } from "@/components/credits";
import { ModelKey } from "@/components/model-key";
import { SefKey } from "@/components/sef-key";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  NativeSelect,
  NativeSelectOption,
} from "@/components/ui/native-select";
import { useIdentity } from "@/hooks/use-identity";
import { ApiError } from "@/lib/api";
import { formatDate } from "@/lib/format";
import {
  deletesInvoices,
  RETENTION_PERIODS,
  setInvoiceRetention,
  storedBefore,
  type Organization,
} from "@/lib/organization";
import { meQuery, organizationQuery } from "@/lib/queries";
import type { Identity } from "@/lib/session";

/** The choice of no period: every invoice is kept until a member deletes it. */
const KEEP = "keep";

/**
 * The visitor's organization: its name, who the visitor is in it, how long it keeps its stored
 * invoices, which its owner sets here (ADR-0039), its key to SEF and its own key to a language
 * model, which its owner sets here too (ADR-0050, ADR-0058), its credits where the server
 * counts them (ADR-0059, ADR-0060), and the visitor's API keys.
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
      <SefKey
        organization={organization.data}
        owner={identity?.role === "owner"}
      />
      <ModelKey
        organization={organization.data}
        owner={identity?.role === "owner"}
      />
      <Credits owner={identity?.role === "owner"} />
      <ApiKeys role={identity?.role ?? null} />
    </div>
  );
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

/** A change of the period, which the card holds so that its outcome outlives the form. */
type Saving = UseMutationResult<Organization, Error, number | null>;

function Retention({
  organization,
  owner,
}: {
  organization: Organization;
  owner: boolean;
}) {
  const t = useTranslations("organization.retention");
  const period = usePeriod();
  const why = useRetentionErrorMessage();
  const saving = useSetRetention();
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
        {owner ? (
          <RetentionForm current={days} saving={saving} />
        ) : (
          <p className="text-muted-foreground">{t("ownersOnly")}</p>
        )}
        {saving.isError && (
          <Alert variant="destructive">
            <AlertDescription>{why(saving.error)}</AlertDescription>
          </Alert>
        )}
        {saving.isSuccess && <p role="status">{t("saved")}</p>}
        {saving.isPending && (
          <p role="status" className="text-muted-foreground">
            {t("saving")}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

/**
 * An owner's choice of the period. A choice that can delete invoices, a period where there was
 * none or a shorter one, is saved only after a second press that says which invoices go.
 */
function RetentionForm({
  current,
  saving,
}: {
  current: number | null;
  saving: Saving;
}) {
  const t = useTranslations("organization.retention");
  const locale = useLocale();
  const period = usePeriod();
  // What the visitor chose, which stays chosen when the period is saved or read again.
  const [chosen, setChosen] = useState(
    current === null ? KEEP : String(current),
  );
  // The period that waits for its second press, and the day before which it deletes.
  const [confirming, setConfirming] = useState<{
    days: number;
    before: Date;
  } | null>(null);
  // The button pressed goes away with the question it asked: the keyboard's focus follows to
  // the button that takes its place, the confirmation's or, cancelled, the form's again.
  const confirmation = useRef<HTMLButtonElement>(null);
  const submit = useRef<HTMLButtonElement>(null);
  const focusing = useRef(false);
  useEffect(() => {
    if (focusing.current) {
      (confirming ? confirmation : submit).current?.focus();
      focusing.current = false;
    }
  }, [confirming]);

  const choice = chosen === KEEP ? null : Number(chosen);
  const periods = [
    ...new Set([...RETENTION_PERIODS, ...(current === null ? [] : [current])]),
  ].sort((a, b) => a - b);

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (choice !== null && deletesInvoices(current, choice)) {
      focusing.current = true;
      setConfirming({
        days: choice,
        before: storedBefore(choice, new Date()),
      });
      return;
    }
    saving.mutate(choice);
  }

  return (
    <form className="grid gap-4" onSubmit={save}>
      <div className="grid gap-2">
        <Label htmlFor="retention">{t("label")}</Label>
        <NativeSelect
          id="retention"
          name="retention"
          value={chosen}
          disabled={saving.isPending || confirming !== null}
          onChange={(event) => {
            setChosen(event.target.value);
            saving.reset();
          }}
        >
          {periods.map((days) => (
            <NativeSelectOption key={days} value={String(days)}>
              {period(days)}
            </NativeSelectOption>
          ))}
          <NativeSelectOption value={KEEP}>{t("keep")}</NativeSelectOption>
        </NativeSelect>
      </div>
      {confirming ? (
        <div className="grid gap-3 rounded-lg border p-4">
          <p className="font-medium">
            {t("confirm", { date: formatDate(locale, confirming.before) })}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              ref={confirmation}
              type="button"
              variant="destructive"
              onClick={() => {
                setConfirming(null);
                saving.mutate(confirming.days);
              }}
            >
              {t("confirmChange")}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                focusing.current = true;
                setConfirming(null);
              }}
            >
              {t("cancel")}
            </Button>
          </div>
        </div>
      ) : (
        <div>
          <Button
            ref={submit}
            type="submit"
            disabled={saving.isPending || choice === current}
          >
            {t("save")}
          </Button>
        </div>
      )}
    </form>
  );
}

/**
 * The change of the period, and what the cache learns from it: the organization the API
 * answers with. A failure whose outcome the page cannot know, an answer that did not come or a
 * server's failure, has the organization read again, to show the period it has; a refusal, the
 * visitor's role, which has changed since the page learned it.
 */
function useSetRetention() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (days: number | null) => setInvoiceRetention(days),
    onSuccess: (organization) => {
      client.setQueryData(organizationQuery.queryKey, organization);
    },
    onError: (error) => {
      if (uncertain(error)) {
        void client.invalidateQueries({ queryKey: organizationQuery.queryKey });
      } else if (error instanceof ApiError && error.status === 403) {
        void client.invalidateQueries({ queryKey: meQuery.queryKey });
      }
    },
  });
}

/** Whether the period may have changed though the page did not hear of it. */
function uncertain(error: unknown): boolean {
  return !(error instanceof ApiError) || [500, 502, 504].includes(error.status);
}

/** Why the period was not changed, in the visitor's language. */
function useRetentionErrorMessage(): (error: unknown) => string {
  const t = useTranslations("organization.retention.errors");
  return (error) => {
    if (!(error instanceof ApiError)) {
      return t("unreachable");
    }
    switch (error.status) {
      case 401:
        return t("signedOut");
      case 403:
        return t("forbidden");
      case 429:
        return t("tooMany", { seconds: error.retryAfter ?? 60 });
      default:
        return uncertain(error) ? t("uncertain") : t("failed");
    }
  };
}
