import createMiddleware from "next-intl/middleware";

import { routing } from "./i18n/routing";

/**
 * A path without a language is sent to the visitor's, as their browser asks for it, or to
 * Serbian (Latin). Files and Next.js's own paths are left alone.
 */
export default createMiddleware(routing);

export const config = {
  matcher: "/((?!_next|_vercel|.*\\..*).*)",
};
