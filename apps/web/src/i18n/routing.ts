import { defineRouting } from "next-intl/routing";

/**
 * The languages of the interface, each the first segment of every path: Serbian in the Latin
 * script first, then English. The locale is a BCP 47 tag, so that dates and numbers are written
 * in Latin letters (`sr` alone means Cyrillic), and the path works with or without a server.
 * The language a visitor picks is kept in the path, not in a cookie.
 */
export const routing = defineRouting({
  locales: ["sr-Latn", "en"],
  defaultLocale: "sr-Latn",
  localePrefix: "always",
  localeCookie: false,
});

export type Locale = (typeof routing.locales)[number];
