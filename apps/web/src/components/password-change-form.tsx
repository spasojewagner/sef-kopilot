"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";

import { refusedAs, useAuthErrorMessage } from "@/components/auth-errors";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useHydrated } from "@/hooks/use-hydrated";
import { ApiError } from "@/lib/api";
import { meQuery } from "@/lib/queries";
import { changePassword, PASSWORD_BOUNDS, SignedOutError } from "@/lib/session";

export function PasswordChangeForm() {
  const t = useTranslations("passwordChange");
  const register = useTranslations("register");
  const messageFor = useAuthErrorMessage();
  const hydrated = useHydrated();
  const client = useQueryClient();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;

    const form = event.currentTarget;
    const fields = new FormData(form);
    const current = String(fields.get("current") ?? "");
    const next = String(fields.get("new") ?? "");
    setError(null);
    setSaved(false);
    if (next !== fields.get("confirm")) {
      setError(t("mismatch"));
      return;
    }

    setPending(true);
    try {
      const identity = await changePassword({
        current_password: current,
        new_password: next,
      });
      client.setQueryData(meQuery.queryKey, identity);
      form.reset();
      setSaved(true);
    } catch (failure) {
      if (failure instanceof SignedOutError) {
        setError(t("signInAgain"));
      } else if (failure instanceof ApiError && failure.status === 401) {
        setError(
          failure.detail === "invalid e-mail address or password"
            ? t("wrongCurrent")
            : t("signInAgain"),
        );
      } else if (
        failure instanceof ApiError &&
        refusedAs(failure, "same_password")
      ) {
        setError(t("same"));
      } else {
        setError(messageFor(failure));
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <Card className="w-full max-w-lg">
      <CardHeader>
        <CardTitle>
          <h2>{t("titleForm")}</h2>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <form method="post" className="grid gap-4" onSubmit={submit}>
          <fieldset disabled={pending} className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="current-password">{t("current")}</Label>
              <Input
                id="current-password"
                name="current"
                type="password"
                autoComplete="current-password"
                required
                maxLength={PASSWORD_BOUNDS.max}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="new-password">{t("new")}</Label>
              <Input
                id="new-password"
                name="new"
                type="password"
                autoComplete="new-password"
                required
                minLength={PASSWORD_BOUNDS.min}
                maxLength={PASSWORD_BOUNDS.max}
                aria-describedby="new-password-hint"
              />
              <p
                id="new-password-hint"
                className="text-sm text-muted-foreground"
              >
                {register("passwordHint", PASSWORD_BOUNDS)}
              </p>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="confirm-password">{t("confirm")}</Label>
              <Input
                id="confirm-password"
                name="confirm"
                type="password"
                autoComplete="new-password"
                required
                maxLength={PASSWORD_BOUNDS.max}
              />
            </div>
          </fieldset>
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          {saved && (
            <p role="status" className="text-sm">
              {t("saved")}
            </p>
          )}
          <Button
            type="submit"
            disabled={!hydrated || pending}
            className="justify-self-start"
          >
            {pending ? t("pending") : t("submit")}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
