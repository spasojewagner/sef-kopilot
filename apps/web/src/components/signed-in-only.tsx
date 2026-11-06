"use client";

import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useSession } from "@/hooks/use-session";
import { Link } from "@/i18n/navigation";

/**
 * ``children`` for a signed-in visitor; for anyone else, the way to sign in. Nothing while the
 * session is not known yet, so that a signed-in visitor never sees the prompt flash by.
 */
export function SignedInOnly({ children }: { children: ReactNode }) {
  const t = useTranslations("signedInOnly");
  const session = useSession();
  if (session.status === "unknown") {
    return null;
  }
  if (session.status === "signed-out") {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t("title")}</CardTitle>
          <CardDescription>{t("description")}</CardDescription>
        </CardHeader>
        <CardFooter className="gap-2">
          <Button asChild>
            <Link href="/sign-in">{t("signIn")}</Link>
          </Button>
          <Button asChild variant="outline">
            <Link href="/register">{t("register")}</Link>
          </Button>
        </CardFooter>
      </Card>
    );
  }
  return children;
}
