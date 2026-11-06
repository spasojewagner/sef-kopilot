"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { Button, buttonVariants } from "@/components/ui/button";
import { useSession } from "@/hooks/use-session";
import { Link, useRouter } from "@/i18n/navigation";
import { meQuery } from "@/lib/queries";
import { signOut } from "@/lib/session";

/**
 * The header's account: who is signed in and the way out, or the way in. Nothing while the
 * session is not known yet, so that a signed-in visitor never sees "Sign in" flash by. The API
 * is asked who the visitor is, which ends here a session that has ended there.
 */
export function Account() {
  const t = useTranslations("account");
  const session = useSession();
  const router = useRouter();
  const me = useQuery({ ...meQuery, enabled: session.status === "signed-in" });

  if (session.status === "unknown") {
    return null;
  }
  if (session.status === "signed-out") {
    return (
      <Link
        href="/sign-in"
        className={buttonVariants({ variant: "outline", size: "sm" })}
      >
        {t("signIn")}
      </Link>
    );
  }
  return (
    <div className="flex min-w-0 items-center gap-2">
      <Link
        href="/invoices"
        className={buttonVariants({ variant: "ghost", size: "sm" })}
      >
        {t("invoices")}
      </Link>
      <span
        className="hidden max-w-56 truncate text-sm text-muted-foreground sm:inline"
        title={(me.data ?? session.identity).organization.name}
      >
        {(me.data ?? session.identity).user.email}
      </span>
      <Button
        variant="outline"
        size="sm"
        onClick={async () => {
          await signOut();
          router.push("/");
        }}
      >
        {t("signOut")}
      </Button>
    </div>
  );
}
