"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useIdentity } from "@/hooks/use-identity";
import { Link } from "@/i18n/navigation";
import { ApiError } from "@/lib/api";
import { formatMoment } from "@/lib/format";
import type { StoredInvoice } from "@/lib/invoices";
import {
  invoiceQuery,
  meQuery,
  organizationQuery,
  submissionsQuery,
} from "@/lib/queries";
import { reasonOf, sendToSef, type Submission } from "@/lib/sef";

/** The roles that send the organization's invoices to SEF (`invoices:send`). */
const SENDERS: ReadonlySet<string> = new Set(["owner", "accountant"]);

/**
 * The stored invoice and SEF (ADR-0051): where it stands in SEF, as SEF last said, which every
 * member who sees the invoice reads, and, for an owner or an accountant, sending it, once it is
 * valid and the organization has a key, after a second press that says it goes in the
 * organization's name.
 */
export function SefSending({ invoice }: { invoice: StoredInvoice }) {
  const t = useTranslations("report.sef");
  const identity = useIdentity();
  const submissions = useQuery(submissionsQuery(invoice.id));
  const sending = useSendToSef(invoice.id);
  const sender = identity !== null && SENDERS.has(identity.role);
  const latest = submissions.data?.[0];

  let shown;
  if (submissions.isPending) {
    shown = <p className="text-muted-foreground">{t("loading")}</p>;
  } else if (submissions.isError) {
    shown = <p className="text-muted-foreground">{t("notLoaded")}</p>;
  } else if (latest === undefined) {
    shown = <p className="text-muted-foreground">{t("never")}</p>;
  } else {
    shown = <Sent submissions={submissions.data} />;
  }

  return (
    <section className="grid gap-3 text-sm" aria-labelledby="sef">
      <h2 id="sef" className="text-lg font-semibold tracking-tight">
        {t("title")}
      </h2>
      {shown}
      {submissions.isSuccess &&
        latest?.state !== "imported" &&
        (sender ? (
          <Sending invoice={invoice} latest={latest} sending={sending} />
        ) : (
          <p className="text-muted-foreground">{t("sendersOnly")}</p>
        ))}
      <Outcome sending={sending} />
    </section>
  );
}

/** What SEF answered the latest time, and the times before it. */
function Sent({ submissions }: { submissions: Submission[] }) {
  const t = useTranslations("report.sef");
  const locale = useLocale();
  const [latest, ...earlier] = submissions;
  const when = (moment: string | null) =>
    moment === null ? "" : formatMoment(locale, moment);
  // A status the page does not know, as SEF says it.
  const statusOf = (status: string) =>
    isKnown(status) ? t(`statuses.${status}`) : status;
  return (
    <div className="grid gap-3">
      <div className="grid gap-1 rounded-lg border p-4">
        {latest.state === "imported" && (
          <>
            <p className="font-medium">
              {t("imported", { when: when(latest.answered_at) })}
            </p>
            <p>
              {latest.sef_status === null
                ? t("notAskedYet")
                : t("standing", { status: statusOf(latest.sef_status) })}
            </p>
            {latest.detail !== null && (
              <p>{t("comment", { comment: latest.detail })}</p>
            )}
            <p className="text-muted-foreground">
              {t("ids", { id: latest.sales_invoice_id ?? "—" })}
              {latest.checked_at !== null &&
                ` ${t("checked", { when: when(latest.checked_at) })}`}
            </p>
          </>
        )}
        {latest.state === "refused" && (
          <>
            <p className="font-medium">
              {latest.refusal === "key"
                ? t("refusedKey", { when: when(latest.answered_at) })
                : t("refused", { when: when(latest.answered_at) })}
            </p>
            {latest.detail !== null && (
              <p>{t("sefSaid", { words: latest.detail })}</p>
            )}
          </>
        )}
        {latest.state === "unconfirmed" && (
          <p className="font-medium">
            {t("unconfirmed", { when: when(latest.sent_at) })}
          </p>
        )}
      </div>
      {earlier.length > 0 && (
        <div className="grid gap-1">
          <h3 className="text-muted-foreground">{t("earlier")}</h3>
          <ul className="grid gap-1">
            {earlier.map((submission) => (
              <li key={submission.id}>
                {t("earlierOne", {
                  when: when(submission.sent_at),
                  state: t(`states.${submission.state}`),
                })}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** The statuses SEF names (`SalesInvoiceStatus`), which the page has words for. */
const STATUSES = [
  "New",
  "Draft",
  "Sending",
  "Sent",
  "Mistake",
  "Approved",
  "Rejected",
  "Cancelled",
  "Storno",
  "Paid",
  "OverDue",
  "Archived",
  "Deleted",
  "Unknown",
] as const;

function isKnown(status: string): status is (typeof STATUSES)[number] {
  return (STATUSES as readonly string[]).includes(status);
}

type Send = ReturnType<typeof useSendToSef>;

/**
 * Sending, for an owner or an accountant: only an invoice the validator passes, only with the
 * organization's key, and only after a second press that names whose name it goes in.
 */
function Sending({
  invoice,
  latest,
  sending,
}: {
  invoice: StoredInvoice;
  latest: Submission | undefined;
  sending: Send;
}) {
  const t = useTranslations("report.sef");
  const identity = useIdentity();
  // Whether the organization has a key matters only for an invoice that may be sent.
  const organization = useQuery({
    ...organizationQuery,
    enabled: invoice.report.valid,
  });
  const [confirming, setConfirming] = useState(false);
  // The button pressed goes away with the question it asked: the keyboard's focus follows to
  // the button that takes its place.
  const confirmation = useRef<HTMLButtonElement>(null);
  const send = useRef<HTMLButtonElement>(null);
  const focusing = useRef(false);
  useEffect(() => {
    if (focusing.current) {
      (confirming ? confirmation : send).current?.focus();
      focusing.current = false;
    }
  }, [confirming]);

  if (!invoice.report.valid) {
    return <p className="text-muted-foreground">{t("invalidFirst")}</p>;
  }
  if (organization.isSuccess && organization.data.sef_key_set_at === null) {
    return (
      <p className="text-muted-foreground">
        {t.rich("noKey", {
          page: (chunks) => (
            <Link href="/organization" className="underline underline-offset-4">
              {chunks}
            </Link>
          ),
        })}
      </p>
    );
  }
  if (sending.isPending) {
    return (
      <p role="status" className="text-muted-foreground">
        {t("sending")}
      </p>
    );
  }
  if (confirming) {
    return (
      <div className="grid gap-3 rounded-lg border p-4">
        <p className="font-medium">
          {t("confirm", {
            number: invoice.summary?.number ?? t("thisInvoice"),
            organization: identity?.organization.name ?? "",
          })}
        </p>
        <div className="flex flex-wrap gap-2">
          <Button
            ref={confirmation}
            type="button"
            onClick={() => {
              setConfirming(false);
              sending.mutate();
            }}
          >
            {t("sendNow")}
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              focusing.current = true;
              setConfirming(false);
            }}
          >
            {t("cancel")}
          </Button>
        </div>
      </div>
    );
  }
  return (
    <div className="grid gap-2">
      {latest?.state === "unconfirmed" && (
        <p className="text-muted-foreground">{t("again")}</p>
      )}
      <div>
        <Button
          ref={send}
          type="button"
          disabled={!organization.isSuccess}
          onClick={() => {
            focusing.current = true;
            sending.reset();
            setConfirming(true);
          }}
        >
          {latest?.state === "unconfirmed" ? t("sendAgain") : t("send")}
        </Button>
      </div>
    </div>
  );
}

/** How the latest sending ended, or why nothing was sent. */
function Outcome({ sending }: { sending: Send }) {
  const t = useTranslations("report.sef");
  const why = useSendErrorMessage();
  if (sending.isSuccess) {
    return <p role="status">{t(`outcomes.${sending.data.state}`)}</p>;
  }
  if (sending.isError) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{why(sending.error)}</AlertDescription>
      </Alert>
    );
  }
  return null;
}

/**
 * Sending the invoice, and what the cache learns: the submission SEF answered, first among the
 * invoice's. A failure whose outcome the page cannot know has the submissions read again, and
 * a refusal what it names: the invoice, the organization's key, or the visitor's role.
 */
function useSendToSef(invoiceId: string) {
  const client = useQueryClient();
  const submissions = submissionsQuery(invoiceId);
  return useMutation({
    mutationFn: () => sendToSef(invoiceId),
    onSuccess: (submission) => {
      client.setQueryData(submissions.queryKey, (before) => [
        submission,
        ...(before ?? []).filter((kept) => kept.id !== submission.id),
      ]);
    },
    onError: (error) => {
      const reason = reasonOf(error);
      if (reason === "no-key") {
        void client.invalidateQueries({ queryKey: organizationQuery.queryKey });
      } else if (reason === "changed" || reason === "invalid") {
        void client.invalidateQueries({
          queryKey: invoiceQuery(invoiceId).queryKey,
        });
      } else if (error instanceof ApiError && error.status === 403) {
        void client.invalidateQueries({ queryKey: meQuery.queryKey });
      } else {
        void client.invalidateQueries({ queryKey: submissions.queryKey });
      }
    },
  });
}

/** Why the invoice was not sent, or why the page does not know, in the visitor's language. */
function useSendErrorMessage(): (error: unknown) => string {
  const t = useTranslations("report.sef.errors");
  return (error) => {
    const reason = reasonOf(error);
    if (reason !== null) {
      return t(reason);
    }
    if (!(error instanceof ApiError)) {
      return t("unreachable");
    }
    switch (error.status) {
      case 401:
        return t("signedOut");
      case 403:
        return t("forbidden");
      case 404:
        return t("gone");
      case 503:
        return t("unavailable");
      default:
        return [500, 502, 504].includes(error.status)
          ? t("uncertain")
          : t("failed");
    }
  };
}
