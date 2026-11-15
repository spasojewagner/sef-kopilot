"use client";

import { useQuery } from "@tanstack/react-query";
import { Building2, ChevronDown, LogOut } from "lucide-react";
import { useTranslations } from "next-intl";

import { buttonVariants } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useSession } from "@/hooks/use-session";
import { Link, useRouter } from "@/i18n/navigation";
import { meQuery } from "@/lib/queries";
import { signOut } from "@/lib/session";

/**
 * The letters of the mark that stands for an account: the first of each of the first two words
 * of its address's name, `marija.petrovic@…` "MP", or its first letter alone.
 */
export function initialsOf(email: string): string {
  const words = email
    .split("@")[0]
    .split(/[._+-]+/)
    .filter((word) => /^\p{L}/u.test(word));
  const letters = words.slice(0, 2).map((word) => word[0]);
  return (letters.length > 0 ? letters.join("") : email[0]).toUpperCase();
}

/**
 * The header's account: a mark with its initials and, on a wide screen, the organization's name,
 * which opens a menu with who is signed in, in which organization and with which role, the way
 * to the organization's settings and the way out; or the way in. Nothing while the session is
 * not known yet, so that a signed-in visitor never sees "Sign in" flash by. The API is asked who
 * the visitor is, which ends here a session that has ended there.
 */
export function Account() {
  const t = useTranslations("account");
  const roles = useTranslations("organization.roles");
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
  const who = me.data ?? session.identity;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        aria-label={t("menu", { email: who.user.email })}
        className="flex min-w-0 items-center gap-2 rounded-full py-1 pr-2 pl-1 text-sm outline-none hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/60 data-[state=open]:bg-accent"
      >
        <span
          aria-hidden="true"
          className="grid size-8 shrink-0 place-items-center rounded-full bg-brand text-xs font-semibold tracking-wide text-brand-foreground"
        >
          {initialsOf(who.user.email)}
        </span>
        <span className="hidden max-w-44 truncate font-medium md:inline">
          {who.organization.name}
        </span>
        <ChevronDown aria-hidden="true" className="size-4 opacity-70" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-72">
        <DropdownMenuLabel className="grid gap-0.5">
          <span className="truncate font-medium">{who.user.email}</span>
          <span className="truncate text-xs font-normal text-muted-foreground">
            {who.organization.name} · {roles(who.role)}
          </span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/organization">
            <Building2 aria-hidden="true" />
            {t("organization")}
          </Link>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onSelect={async () => {
            await signOut();
            router.push("/");
          }}
        >
          <LogOut aria-hidden="true" />
          {t("signOut")}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
