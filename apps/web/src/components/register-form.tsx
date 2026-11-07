"use client";

import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import type { FormEvent } from "react";

import { useAuthErrorMessage } from "@/components/auth-errors";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useHydrated } from "@/hooks/use-hydrated";
import { Link, useRouter } from "@/i18n/navigation";
import { register } from "@/lib/session";

/** The API's bounds on a new password (ADR-0012). */
const PASSWORD = { min: 12, max: 128 };

/**
 * Creates an account, its organization with the visitor as owner, and signs in. As signing in
 * is, the form is sent by the page's script only, never with its password in the address.
 */
export function RegisterForm() {
  const t = useTranslations("register");
  const messageFor = useAuthErrorMessage();
  const router = useRouter();
  const hydrated = useHydrated();
  const registering = useMutation({
    mutationFn: register,
    onSuccess: () => router.replace("/"),
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    registering.mutate({
      email: String(form.get("email") ?? ""),
      password: String(form.get("password") ?? ""),
      organizationName: String(form.get("organization") ?? ""),
    });
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xl">
          <h1>{t("title")}</h1>
        </CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form method="post" className="grid gap-4" onSubmit={submit}>
          <div className="grid gap-2">
            <Label htmlFor="email">{t("email")}</Label>
            <Input
              id="email"
              name="email"
              type="email"
              autoComplete="email"
              required
              maxLength={320}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="password">{t("password")}</Label>
            <Input
              id="password"
              name="password"
              type="password"
              autoComplete="new-password"
              required
              minLength={PASSWORD.min}
              maxLength={PASSWORD.max}
              aria-describedby="password-hint"
            />
            <p id="password-hint" className="text-sm text-muted-foreground">
              {t("passwordHint", PASSWORD)}
            </p>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="organization">{t("organization")}</Label>
            <Input
              id="organization"
              name="organization"
              autoComplete="organization"
              required
              maxLength={200}
            />
          </div>
          {registering.isError && (
            <Alert variant="destructive">
              <AlertDescription>
                {messageFor(registering.error)}
              </AlertDescription>
            </Alert>
          )}
          <Button type="submit" disabled={!hydrated || registering.isPending}>
            {registering.isPending ? t("pending") : t("submit")}
          </Button>
        </form>
      </CardContent>
      <CardFooter className="gap-1 text-sm text-muted-foreground">
        {t("haveAccount")}
        <Link
          className="text-foreground underline underline-offset-4"
          href="/sign-in"
        >
          {t("signIn")}
        </Link>
      </CardFooter>
    </Card>
  );
}
