import { createNavigation } from "next-intl/navigation";

import { routing } from "./routing";

/** Links and navigation that keep the visitor's language in the path. */
export const { Link, getPathname, redirect, usePathname, useRouter } =
  createNavigation(routing);
