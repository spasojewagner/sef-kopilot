import { notFound } from "next/navigation";

/** Nothing here can be prerendered: the page only answers 404, in the path's language. */
export const instant = false;

/** Any other path under a language is a page that does not exist, shown in that language. */
export default function UnknownPage(): never {
  notFound();
}
