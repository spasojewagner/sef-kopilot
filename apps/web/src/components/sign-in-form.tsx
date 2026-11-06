"use client";

import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";

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
import { useSession } from "@/hooks/use-session";
import { Link, useRouter } from "@/i18n/navigation";
import { organizationsToChoose, signIn, type Membership } from "@/lib/session";

interface Credentials {
  email: string;
  password: string;
}

/**
 * Signs a visitor in with their address and password. A member of several organizations
 * chooses the one to work in, and the API is asked again for it.
 */
export function SignInForm() {
  const t = useTranslations("signIn");
  const messageFor = useAuthErrorMessage();
  const router = useRouter();
  const session = useSession();
  const [choice, setChoice] = useState<{
    credentials: Credentials;
    organizations: Membership[];
  } | null>(null);
  const signingIn = useMutation({
    mutationFn: signIn,
    onSuccess: () => router.replace("/"),
    onError: (error, credentials) => {
      const organizations = organizationsToChoose(error);
      if (organizations !== null) {
        setChoice({ credentials, organizations });
      }
    },
  });

  if (session.status === "signed-in" && signingIn.isIdle) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-xl">
            <h1>{t("title")}</h1>
          </CardTitle>
          <CardDescription>
            {t("signedIn", { email: session.identity.user.email })}
          </CardDescription>
        </CardHeader>
        <CardFooter>
          <Button asChild variant="outline">
            <Link href="/">{t("home")}</Link>
          </Button>
        </CardFooter>
      </Card>
    );
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setChoice(null);
    signingIn.mutate({
      email: String(form.get("email") ?? ""),
      password: String(form.get("password") ?? ""),
    });
  }

  const failure =
    signingIn.isError && organizationsToChoose(signingIn.error) === null
      ? messageFor(signingIn.error)
      : null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xl">
          <h1>{t("title")}</h1>
        </CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-6">
        <form className="grid gap-4" onSubmit={submit}>
          <div className="grid gap-2">
            <Label htmlFor="email">{t("email")}</Label>
            <Input
              id="email"
              name="email"
              type="email"
              autoComplete="username"
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
              autoComplete="current-password"
              required
              maxLength={128}
            />
          </div>
          {failure !== null && (
            <Alert variant="destructive">
              <AlertDescription>{failure}</AlertDescription>
            </Alert>
          )}
          <Button type="submit" disabled={signingIn.isPending}>
            {signingIn.isPending ? t("pending") : t("submit")}
          </Button>
        </form>
        {choice !== null && (
          <fieldset className="grid gap-2">
            <legend className="mb-2 text-sm">{t("chooseOrganization")}</legend>
            {choice.organizations.map((membership) => (
              <Button
                key={membership.organization.id}
                type="button"
                variant="outline"
                disabled={signingIn.isPending}
                onClick={() =>
                  signingIn.mutate({
                    ...choice.credentials,
                    organizationId: membership.organization.id,
                  })
                }
              >
                {membership.organization.name}
              </Button>
            ))}
          </fieldset>
        )}
      </CardContent>
      <CardFooter className="gap-1 text-sm text-muted-foreground">
        {t("noAccount")}
        <Link
          className="text-foreground underline underline-offset-4"
          href="/register"
        >
          {t("register")}
        </Link>
      </CardFooter>
    </Card>
  );
}
