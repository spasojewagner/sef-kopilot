"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import {
  invoiceQuery,
  invoicesQuery,
  repairQuery,
  repairsQuery,
} from "@/lib/queries";
import {
  conflictOf,
  decideRepair,
  type Decision,
  type Repair,
} from "@/lib/repairs";

/** What refuses an approval for good: asking again would be refused again. */
const FUTILE = new Set([
  "changes-nothing",
  "invoice-changed",
  "outcome-changed",
]);

/**
 * A person's decision on a repair that waits for one: approve it, which makes the invoice the
 * patched document, after a second press that says so; or reject it. Nothing while the repair
 * waits for no decision, unless it was decided, or refused, here.
 */
export function RepairDecision({ repair }: { repair: Repair }) {
  const t = useTranslations("decision");
  const why = useDecisionErrorMessage();
  const [confirming, setConfirming] = useState(false);
  const deciding = useDecide(repair);
  // The button pressed goes away with the question it asked: the keyboard's focus follows to
  // the button that takes its place, the confirmation's or, cancelled, the approval's again.
  const confirmation = useRef<HTMLButtonElement>(null);
  const approval = useRef<HTMLButtonElement>(null);
  const focusing = useRef(false);
  useEffect(() => {
    if (focusing.current) {
      (confirming ? confirmation : approval).current?.focus();
      focusing.current = false;
    }
  }, [confirming]);
  const ask = (confirm: boolean) => {
    focusing.current = true;
    setConfirming(confirm);
  };

  if (deciding.isSuccess) {
    return (
      <p role="status" className="text-sm">
        {deciding.variables === "approval" ? t("approved") : t("rejected")}
      </p>
    );
  }
  if (deciding.isPending) {
    return (
      <p role="status" className="text-sm text-muted-foreground">
        {deciding.variables === "approval" ? t("approving") : t("rejecting")}
      </p>
    );
  }
  const waits = repair.status === "proposed";
  if (!waits && !deciding.isError) {
    return null;
  }
  const approvable =
    repair.changed && !FUTILE.has(conflictOf(deciding.error) ?? "");
  const decide = (decision: Decision) => {
    setConfirming(false);
    deciding.mutate(decision);
  };
  return (
    <section className="grid gap-3" aria-labelledby="decision">
      <h2 id="decision" className="text-lg font-semibold tracking-tight">
        {t("title")}
      </h2>
      {deciding.isError && (
        <Alert variant="destructive">
          <AlertDescription>{why(deciding.error)}</AlertDescription>
        </Alert>
      )}
      {waits && (
        <div className="grid gap-3 rounded-lg border p-4 text-sm">
          {repair.changed ? (
            <>
              <p>{t("whatApprovalDoes")}</p>
              {!repair.valid && (
                <p className="text-muted-foreground">{t("stillInvalid")}</p>
              )}
            </>
          ) : (
            <p>{t("nothingToApprove")}</p>
          )}
          {confirming ? (
            <div className="grid gap-3">
              <p className="font-medium">{t("confirm")}</p>
              <div className="flex flex-wrap gap-2">
                <Button ref={confirmation} onClick={() => decide("approval")}>
                  {t("confirmApproval")}
                </Button>
                <Button variant="outline" onClick={() => ask(false)}>
                  {t("cancel")}
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex flex-wrap gap-2">
              {approvable && (
                <Button ref={approval} onClick={() => ask(true)}>
                  {t("approve")}
                </Button>
              )}
              <Button variant="outline" onClick={() => decide("rejection")}>
                {t("reject")}
              </Button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

/**
 * The decision on ``repair``, and what the cache learns from it. An approval changes the
 * invoice: what is kept under its key, its report, explanations and repairs, and the list's
 * verdicts are read again when next shown. A rejection changes the invoice's list of repairs
 * alone. A failure whose outcome the page cannot know, an answer that did not come, or a
 * decision made meanwhile, has the repair read again, to show where it stands.
 */
function useDecide(repair: Repair) {
  const client = useQueryClient();
  const invoice = repair.invoice_id;
  const decided = repairQuery(invoice, repair.id).queryKey;
  return useMutation({
    mutationFn: (decision: Decision) =>
      decideRepair(invoice, repair.id, decision),
    onSuccess: (answer, decision) => {
      if (decision === "approval") {
        void client.invalidateQueries({
          queryKey: invoiceQuery(invoice).queryKey,
          refetchType: "none",
        });
        void client.invalidateQueries({
          queryKey: invoicesQuery.queryKey,
          refetchType: "none",
        });
      } else {
        void client.invalidateQueries({
          queryKey: repairsQuery(invoice).queryKey,
          exact: true,
          refetchType: "none",
        });
      }
      // After the invalidation, so that the decided repair is fresh on its page.
      client.setQueryData(decided, answer);
    },
    onError: (error) => {
      if (uncertain(error) || conflictOf(error) === "decided") {
        void client.invalidateQueries({ queryKey: decided, exact: true });
      }
    },
  });
}

/**
 * Whether the decision may have been made though the page did not hear of it: no answer, or a
 * server's failure that may have come after the decision was recorded.
 */
function uncertain(error: unknown): boolean {
  return !(error instanceof ApiError) || [500, 502, 504].includes(error.status);
}

/** Why the decision was not recorded, in the visitor's language. */
function useDecisionErrorMessage(): (error: unknown) => string {
  const t = useTranslations("decision.errors");
  return (error) => {
    if (!(error instanceof ApiError)) {
      // The browser's DOMException, which need not be an Error of this realm.
      const name =
        typeof error === "object" && error !== null && "name" in error
          ? error.name
          : null;
      return name === "TimeoutError" ? t("tooSlow") : t("unreachable");
    }
    switch (conflictOf(error)) {
      case "decided":
        return t("decided");
      case "changes-nothing":
        return t("changesNothing");
      case "invoice-changed":
        return t("invoiceChanged");
      case "outcome-changed":
        return t("outcomeChanged");
    }
    const seconds = error.retryAfter;
    switch (error.status) {
      case 403:
        return t("inPerson");
      case 404:
        return t("notFound");
      case 429:
        return t("tooMany", { seconds: seconds ?? 60 });
      case 503:
        return seconds === null ? t("unavailable") : t("busy", { seconds });
      case 507:
        return t("storageFull");
      default:
        return uncertain(error) ? t("uncertain") : t("failed");
    }
  };
}
