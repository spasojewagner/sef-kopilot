import { ArrowLeft } from "lucide-react";
import type { ComponentProps } from "react";

import { Link } from "@/i18n/navigation";
import { cn } from "@/lib/utils";

/**
 * The way back to the page a page belongs to, above its heading: quiet, so that it does not
 * compete with the page's own actions, and named by its words alone, the arrow being hidden.
 */
export function BackLink({
  className,
  children,
  ...props
}: ComponentProps<typeof Link>) {
  return (
    <Link
      {...props}
      className={cn(
        "inline-flex w-fit items-center gap-1.5 rounded-sm text-sm font-medium text-muted-foreground outline-none hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50",
        className,
      )}
    >
      <ArrowLeft aria-hidden="true" className="size-4" />
      {children}
    </Link>
  );
}
