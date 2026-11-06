import type messages from "../../messages/sr-Latn.json";
import type { routing } from "./routing";

// The keys of the Serbian messages, and the interface's languages, checked by the compiler:
// a key that does not exist, or a language the routing does not know, does not compile.
declare module "next-intl" {
  interface AppConfig {
    Locale: (typeof routing.locales)[number];
    Messages: typeof messages;
  }
}
