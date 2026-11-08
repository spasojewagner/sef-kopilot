"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { Check, Plug } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useId } from "react";

import { Fact } from "@/components/fact";
import { SignInForm } from "@/components/sign-in-form";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useSession } from "@/hooks/use-session";
import { ApiError } from "@/lib/api";
import { formatTime } from "@/lib/format";
import {
  approveAuthorizationRequest,
  destinationOf,
  publisherOf,
  refuseAuthorizationRequest,
  type AuthorizationRequest,
} from "@/lib/oauth";
import { authorizationRequestQuery, meQuery } from "@/lib/queries";
import { signOut, type Identity } from "@/lib/session";

/** The message that says what each scope lets a client do. */
const SCOPES: ReadonlyMap<string, "invoicesValidate" | "invoicesSubmit"> =
  new Map([
    ["invoices:validate", "invoicesValidate"],
    ["invoices:submit", "invoicesSubmit"],
  ]);

type Choice = "approve" | "refuse";

/** Leaves for the client's address, with its answer: the page's part ends there. */
function leaveFor(uri: string): void {
  window.location.assign(uri);
}

/** After a sign-in on this page, the page goes on: it shows the request once it can be read. */
function stay(): void {
  // Nothing to do: the page reads the session.
}

/**
 * Where the API sends a person whom an MCP client asks to act for (ADR-0044): what the client
 * asks, where the person returns, the organization it will work in, and the decision, which
 * the API answers with the client's address to go back to. A visitor who is not signed in signs
 * in here, and stays. The client's name is its own, unchecked; the address the person returns
 * to is what they can check. ``goTo`` leaves the page; a test watches it instead.
 */
export function AppConsent({
  requestId,
  goTo = leaveFor,
}: {
  requestId: string | null;
  goTo?: (uri: string) => void;
}) {
  const t = useTranslations("consent");
  const session = useSession();
  if (requestId === null) {
    return <Notice title={t("missingTitle")} text={t("missing")} />;
  }
  if (session.status === "unknown") {
    return null;
  }
  if (session.status === "signed-out") {
    return (
      <div className="grid gap-6">
        <p className="flex gap-3 rounded-lg border bg-card px-4 py-3 text-sm">
          <Plug
            aria-hidden="true"
            className="mt-0.5 size-4 shrink-0 text-brand"
          />
          {t("signInFirst")}
        </p>
        <SignInForm onSignedIn={stay} />
      </div>
    );
  }
  return <Decide id={requestId} identity={session.identity} goTo={goTo} />;
}

/** Whether the API said the request no longer waits: it expired, or was decided. */
function isGone(error: Error | null): boolean {
  return error instanceof ApiError && error.status === 404;
}

function Decide({
  id,
  identity,
  goTo,
}: {
  id: string;
  identity: Identity;
  goTo: (uri: string) => void;
}) {
  const t = useTranslations("consent");
  const asked = useQuery(authorizationRequestQuery(id));
  const deciding = useMutation({
    mutationFn: (choice: Choice) =>
      choice === "approve"
        ? approveAuthorizationRequest(id)
        : refuseAuthorizationRequest(id),
    onSuccess: (decision) => goTo(decision.redirect_uri),
  });

  if (isGone(asked.error) || isGone(deciding.error)) {
    return <Notice title={t("goneTitle")} text={t("gone")} />;
  }
  if (asked.isPending) {
    return (
      <p role="status" className="text-sm text-muted-foreground">
        {t("loading")}
      </p>
    );
  }
  if (asked.isError) {
    return (
      <div className="grid justify-items-start gap-4">
        <Alert variant="destructive">
          <AlertDescription>{t("notLoaded")}</AlertDescription>
        </Alert>
        <Button variant="outline" onClick={() => void asked.refetch()}>
          {t("retry")}
        </Button>
      </div>
    );
  }
  const failed =
    deciding.error === null
      ? null
      : deciding.error instanceof ApiError && deciding.error.status === 403
        ? t("forbidden")
        : t("failed");
  return (
    <Asked
      request={asked.data}
      identity={identity}
      deciding={deciding.isPending ? (deciding.variables ?? null) : null}
      leaving={deciding.isSuccess}
      failed={failed}
      decide={(choice) => deciding.mutate(choice)}
    />
  );
}

function Asked({
  request,
  identity,
  deciding,
  leaving,
  failed,
  decide,
}: {
  request: AuthorizationRequest;
  identity: Identity;
  deciding: Choice | null;
  leaving: boolean;
  failed: string | null;
  decide: (choice: Choice) => void;
}) {
  const t = useTranslations("consent");
  const locale = useLocale();
  const scopesId = useId();
  // Who the visitor is now, as the API says, once it has: the organization the client will
  // work in is the one the session is in.
  const me = useQuery(meQuery);
  const who = me.data ?? identity;
  const destination = destinationOf(request.redirect_uri);
  const publisher = publisherOf(request.client_id);
  const busy = deciding !== null || leaving;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xl">
          <h1>{t("title")}</h1>
        </CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-6">
        <dl className="grid gap-4 text-sm [overflow-wrap:anywhere]">
          <Fact
            term={t("app")}
            value={request.client_name ?? t("unnamed")}
            note={t("unchecked")}
          />
          {publisher !== null && (
            <Fact
              term={t("describedAt")}
              value={publisher}
              note={t("publisher")}
            />
          )}
          <Fact
            term={t("returnsTo")}
            value={destination.address}
            note={destination.local ? t("local") : undefined}
          />
          <Fact
            term={t("worksIn")}
            value={who.organization.name}
            note={t("as", { email: who.user.email })}
          >
            <Button
              variant="link"
              className="h-auto p-0 underline"
              disabled={busy}
              onClick={() => void signOut()}
            >
              {t("otherAccount")}
            </Button>
          </Fact>
        </dl>
        <div className="grid gap-2 text-sm">
          <h2 id={scopesId} className="text-muted-foreground">
            {t("may")}
          </h2>
          <ul aria-labelledby={scopesId} className="grid gap-2">
            {request.scopes.map((scope) => {
              const message = SCOPES.get(scope);
              return (
                <li key={scope} className="flex gap-2 font-medium">
                  <Check
                    aria-hidden="true"
                    className="mt-0.5 size-4 shrink-0 text-success"
                  />
                  {message === undefined ? scope : t(`scopes.${message}`)}
                </li>
              );
            })}
          </ul>
        </div>
        <p className="text-sm text-muted-foreground">
          {t("waits", { time: formatTime(locale, request.expires_at) })}
        </p>
        {failed !== null && (
          <Alert variant="destructive">
            <AlertDescription>{failed}</AlertDescription>
          </Alert>
        )}
        <p role="status" className="text-sm empty:hidden">
          {leaving ? t("returning", { address: destination.address }) : null}
        </p>
      </CardContent>
      <CardFooter className="flex-wrap gap-2">
        <Button disabled={busy} onClick={() => decide("approve")}>
          {deciding === "approve" ? t("allowing") : t("allow")}
        </Button>
        <Button
          variant="outline"
          disabled={busy}
          onClick={() => decide("refuse")}
        >
          {deciding === "refuse" ? t("denying") : t("deny")}
        </Button>
      </CardFooter>
    </Card>
  );
}

/** A page that has no request to show: why, and what to do. */
function Notice({ title, text }: { title: string; text: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xl">
          <h1>{title}</h1>
        </CardTitle>
        <CardDescription>{text}</CardDescription>
      </CardHeader>
    </Card>
  );
}
