"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api";
import {
  GRANTED,
  KEY_PERMISSIONS,
  issueKey,
  revokeKey,
  type ApiKey,
  type IssuedKey,
  type KeyPermission,
} from "@/lib/api-keys";
import { formatMoment } from "@/lib/format";
import { apiKeysQuery } from "@/lib/queries";

/**
 * The visitor's API keys: for each machine that acts for them, such as an ERP, what it may do
 * and when it was last used; a new key, shown once; and a key revoked at once (ADR-0017).
 */
export function ApiKeys({ role }: { role: string | null }) {
  const t = useTranslations("organization.keys");
  const keys = useQuery(apiKeysQuery);
  const [issued, setIssued] = useState<IssuedKey | null>(null);
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>{t("title")}</h2>
        </CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-6 text-sm">
        {issued !== null && (
          <Issued issued={issued} onDone={() => setIssued(null)} />
        )}
        {keys.isPending && (
          <p role="status" className="text-muted-foreground">
            {t("loading")}
          </p>
        )}
        {keys.isError && (
          <Alert variant="destructive">
            <AlertDescription>{t("notLoaded")}</AlertDescription>
          </Alert>
        )}
        {keys.isSuccess &&
          (keys.data.length === 0 ? (
            <p className="text-muted-foreground">{t("none")}</p>
          ) : (
            <ul className="grid gap-3" aria-label={t("listed")}>
              {keys.data.map((key) => (
                <KeyItem key={key.id} apiKey={key} />
              ))}
            </ul>
          ))}
        <IssueForm role={role} onIssued={setIssued} />
      </CardContent>
    </Card>
  );
}

/** A key just issued: the one time it is shown, until the visitor says they have kept it. */
function Issued({ issued, onDone }: { issued: IssuedKey; onDone: () => void }) {
  const t = useTranslations("organization.keys");
  const [copied, setCopied] = useState(false);
  const shown = useRef<HTMLElement>(null);
  useEffect(() => {
    shown.current?.focus();
  }, []);
  return (
    <section
      ref={shown}
      tabIndex={-1}
      aria-labelledby="issued-key"
      className="grid gap-3 rounded-md border border-primary/40 bg-primary/5 p-4"
    >
      <h3 id="issued-key" className="font-medium">
        {t("issued", { name: issued.name })}
      </h3>
      <p>{t("onlyOnce")}</p>
      <code className="block rounded bg-background p-2 font-mono text-xs break-all">
        {issued.key}
      </code>
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          variant="outline"
          onClick={() => {
            void navigator.clipboard?.writeText(issued.key).then(() => {
              setCopied(true);
            });
          }}
        >
          {copied ? t("copied") : t("copy")}
        </Button>
        <Button type="button" onClick={onDone}>
          {t("kept")}
        </Button>
      </div>
    </section>
  );
}

/** A key the visitor may see, and its revocation, which asks once more before it happens. */
function KeyItem({ apiKey }: { apiKey: ApiKey }) {
  const t = useTranslations("organization.keys");
  const locale = useLocale();
  const revoking = useRevoke();
  const why = useErrorMessage();
  const [confirming, setConfirming] = useState(false);
  return (
    <li className="grid gap-2 rounded-md border p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="font-medium">{apiKey.name}</span>
        <code className="font-mono text-xs text-muted-foreground">
          {apiKey.prefix}…
        </code>
      </div>
      <dl className="grid gap-x-4 gap-y-1 sm:grid-cols-[max-content_1fr]">
        <dt className="text-muted-foreground">{t("allows")}</dt>
        <dd>
          {/* A key holds only the permissions a key may hold, said in the form's order. */}
          {KEY_PERMISSIONS.filter((permission) =>
            (apiKey.permissions as string[]).includes(permission),
          )
            .map((permission) => t(`permissions.${permission}`))
            .join(", ")}
        </dd>
        <dt className="text-muted-foreground">{t("lastUsed")}</dt>
        <dd>
          {apiKey.last_used_at === null
            ? t("never")
            : formatMoment(locale, apiKey.last_used_at)}
        </dd>
        <dt className="text-muted-foreground">{t("created")}</dt>
        <dd>{formatMoment(locale, apiKey.created_at)}</dd>
        {apiKey.expires_at !== null && (
          <>
            <dt className="text-muted-foreground">{t("expires")}</dt>
            <dd>{formatMoment(locale, apiKey.expires_at)}</dd>
          </>
        )}
      </dl>
      {confirming ? (
        <div className="grid gap-2" role="group" aria-label={t("revoke")}>
          <p>{t("confirmRevoke", { name: apiKey.name })}</p>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="destructive"
              disabled={revoking.isPending}
              onClick={() => revoking.mutate(apiKey.id)}
            >
              {t("revokeNow")}
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={revoking.isPending}
              onClick={() => {
                setConfirming(false);
                revoking.reset();
              }}
            >
              {t("cancel")}
            </Button>
          </div>
        </div>
      ) : (
        <div>
          <Button
            type="button"
            variant="outline"
            onClick={() => setConfirming(true)}
          >
            {t("revoke")}
          </Button>
        </div>
      )}
      {revoking.isError && (
        <Alert variant="destructive">
          <AlertDescription>{why(revoking.error)}</AlertDescription>
        </Alert>
      )}
    </li>
  );
}

/**
 * A new key: what it is for, what it may do, among what the visitor's role grants, and, if it
 * should stop working, when.
 */
function IssueForm({
  role,
  onIssued,
}: {
  role: string | null;
  onIssued: (issued: IssuedKey) => void;
}) {
  const t = useTranslations("organization.keys");
  const why = useErrorMessage();
  const offered = GRANTED[role ?? "client"] ?? GRANTED.client;
  const [name, setName] = useState("");
  const [chosen, setChosen] = useState<KeyPermission[]>([
    "invoices:validate",
    "invoices:submit",
  ]);
  const [expires, setExpires] = useState("");
  const client = useQueryClient();
  const issuing = useMutation({
    mutationFn: issueKey,
    onSuccess: (issued) => {
      onIssued(issued);
      setName("");
      setExpires("");
      void client.invalidateQueries({ queryKey: apiKeysQuery.queryKey });
    },
  });

  function issue(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    issuing.mutate({
      name: name.trim(),
      permissions: chosen.filter((permission) => offered.includes(permission)),
      expiresAt: expires === "" ? null : dayAfter(expires),
    });
  }

  const nothing = chosen.every((permission) => !offered.includes(permission));
  return (
    <form className="grid gap-4 border-t pt-4" onSubmit={issue}>
      <h3 className="font-medium">{t("new")}</h3>
      <div className="grid gap-2">
        <Label htmlFor="key-name">{t("name")}</Label>
        <Input
          id="key-name"
          name="name"
          required
          maxLength={100}
          value={name}
          placeholder={t("namePlaceholder")}
          onChange={(event) => {
            setName(event.target.value);
            issuing.reset();
          }}
        />
      </div>
      <fieldset className="grid gap-2">
        <legend className="mb-1 text-sm font-medium">{t("allows")}</legend>
        {offered.map((permission) => (
          <label key={permission} className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={chosen.includes(permission)}
              onChange={(event) => {
                setChosen((before) =>
                  event.target.checked
                    ? [...before, permission]
                    : before.filter((kept) => kept !== permission),
                );
                issuing.reset();
              }}
            />
            {t(`permissions.${permission}`)}
          </label>
        ))}
      </fieldset>
      <div className="grid gap-2">
        <Label htmlFor="key-expires">{t("expiresOn")}</Label>
        <Input
          id="key-expires"
          name="expires"
          type="date"
          value={expires}
          onChange={(event) => setExpires(event.target.value)}
          className="max-w-48"
        />
        <p className="text-muted-foreground">{t("expiresHint")}</p>
      </div>
      <div>
        <Button
          type="submit"
          disabled={issuing.isPending || nothing || name.trim() === ""}
        >
          {issuing.isPending ? t("issuing") : t("issue")}
        </Button>
      </div>
      {issuing.isError && (
        <Alert variant="destructive">
          <AlertDescription>{why(issuing.error)}</AlertDescription>
        </Alert>
      )}
    </form>
  );
}

/** The start of the day after ``day`` (`2026-12-31`), in the visitor's time: a key works
 * through the day chosen. */
export function dayAfter(day: string): Date {
  const [year, month, date] = day.split("-").map(Number);
  return new Date(year, month - 1, date + 1);
}

/** A key's revocation; the list is read again, whatever the answer, to show the keys that work. */
function useRevoke() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: revokeKey,
    onSettled: () => {
      void client.invalidateQueries({ queryKey: apiKeysQuery.queryKey });
    },
  });
}

/** Why a key was not issued or revoked, in the visitor's language. */
function useErrorMessage(): (error: unknown) => string {
  const t = useTranslations("organization.keys.errors");
  return (error) => {
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
      case 409:
        return t("tooMany");
      case 422:
        return t("invalid");
      case 429:
        return t("slowDown", { seconds: error.retryAfter ?? 60 });
      default:
        return t("failed");
    }
  };
}
