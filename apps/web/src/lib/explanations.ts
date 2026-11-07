import { ApiError, type Schemas } from "@/lib/api";
import { authorized } from "@/lib/session";

/** The explanations of a stored invoice's report, and the rules they leave for later. */
export type Explained = Schemas["Explained"];
/** One rule's explanation, with the passages it cites. */
export type Explanation = Schemas["Explanation"];
/** A passage of an official document, dated, as an explanation cites it. */
export type Citation = Schemas["Citation"];
/** The languages the explanations are written in. */
export type Language = Explained["language"];

/**
 * How long the explanations may take. The API stops the language model after half a minute by
 * default, and says which rules it did not reach.
 */
export const EXPLAIN_TIMEOUT_MS = 60_000;

/** The language of the explanations on a page in ``locale``. */
export function languageOf(locale: string): Language {
  return locale === "en" ? "en" : "sr";
}

const explanationsOf = (id: string, language: Language) =>
  `/invoices/${encodeURIComponent(id)}/explanations?${new URLSearchParams({ language })}`;

/**
 * The explanations of the stored invoice ``id``'s report, in ``language``: what each rule
 * requires, why the invoice fails it and what to change, citing the passages that apply on its
 * day. The API reads those it keeps for the report; without them, the language model writes
 * them, and the API keeps them when every rule is explained (ADR-0040).
 */
export function explainInvoice(
  id: string,
  language: Language,
  signal?: AbortSignal,
): Promise<Explained> {
  return authorized<Explained>(explanationsOf(id, language), {
    method: "POST",
    signal,
    timeoutMs: EXPLAIN_TIMEOUT_MS,
  });
}

/**
 * The explanations the API keeps for the stored invoice ``id``'s report in ``language``, which
 * reading asks the language model nothing; null when none are kept, which the API answers with a
 * 204. Reading them is a convenience: when it fails, null too, and asking
 * ({@link explainInvoice}) reads them as well.
 */
export async function keptExplanations(
  id: string,
  language: Language,
  signal?: AbortSignal,
): Promise<Explained | null> {
  try {
    const path = explanationsOf(id, language);
    const kept = await authorized<Explained | undefined>(path, { signal });
    return kept ?? null;
  } catch (error) {
    if (signal?.aborted && !(error instanceof ApiError)) {
      throw error;
    }
    return null;
  }
}

/** ``text``'s language when it is written in Cyrillic, as the Serbian law is. */
export function cyrillic(text: string): "sr-Cyrl" | undefined {
  return /\p{Script=Cyrillic}/u.test(text) ? "sr-Cyrl" : undefined;
}
