"use client";

import { Building2, FileCheck2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { Suspense } from "react";

import { buttonVariants } from "@/components/ui/button";
import { useSession } from "@/hooks/use-session";
import { Link, usePathname } from "@/i18n/navigation";
import { cn } from "@/lib/utils";

/** The parts of the application a member works in, each with the path it begins at. */
const SECTIONS = [
  { path: "/invoices", name: "invoices", Icon: FileCheck2 },
  { path: "/organization", name: "organization", Icon: Building2 },
] as const;

/**
 * Where a page stands among the sections: `page` on the section's own page, `true` on a page
 * within it (an invoice's report is within the invoices), nothing elsewhere.
 */
export function currentness(
  pathname: string,
  section: string,
): "page" | "true" | undefined {
  if (pathname === section) {
    return "page";
  }
  return pathname.startsWith(`${section}/`) ? "true" : undefined;
}

/**
 * The header's sections, for a member who is signed in, the one the page is in marked with a
 * line along the header's edge. On a phone a section is an icon, which names itself to a
 * screen reader, so that the header fits 320 px. A page whose path is known only when it is
 * asked for marks its section then, a moment after the rest (as the languages do).
 */
export function Sections() {
  const header = useTranslations("header");
  const session = useSession();

  if (session.status !== "signed-in") {
    return null;
  }
  return (
    <nav aria-label={header("sections")} data-sections="">
      <Suspense fallback={<SectionLinks pathname={null} />}>
        <CurrentSectionLinks />
      </Suspense>
    </nav>
  );
}

/** The sections, the page's marked. */
function CurrentSectionLinks() {
  return <SectionLinks pathname={usePathname()} />;
}

function SectionLinks({ pathname }: { pathname: string | null }) {
  const t = useTranslations("account");
  return (
    <ul className="flex items-center gap-0.5 sm:gap-1">
      {SECTIONS.map(({ path, name, Icon }) => (
        <li key={path}>
          <Link
            href={path}
            aria-current={
              pathname === null ? undefined : currentness(pathname, path)
            }
            className={cn(
              buttonVariants({ variant: "ghost", size: "sm" }),
              "relative text-muted-foreground hover:text-foreground aria-[current]:text-foreground max-sm:px-2",
              // The mark of the current section, on the header's bottom edge.
              "after:absolute after:inset-x-2 after:-bottom-[17px] after:h-0.5 after:rounded-full after:bg-brand after:opacity-0 after:transition-opacity aria-[current]:after:opacity-100",
            )}
          >
            <Icon aria-hidden="true" className="sm:hidden" />
            <span className="sr-only sm:not-sr-only">{t(name)}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
