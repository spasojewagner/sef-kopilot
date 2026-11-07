"use client";

import {
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import {
  type Citation,
  cyrillic,
  type Explained,
  type Explanation,
  languageOf,
} from "@/lib/explanations";
import { formatDay } from "@/lib/format";
import { askForExplanations, explanationsQuery } from "@/lib/queries";

/**
 * The explanations of a stored invoice's report, null while none are kept or written, and how
 * the visitor asks for them.
 */
export interface Explaining {
  explained: UseQueryResult<Explained | null>;
  ask: () => void;
}

/**
 * The explanations of the stored invoice ``id``'s report, in the page's language. Those the API
 * keeps for the report are shown at once, and reading them asks the language model nothing
 * (ADR-0040); otherwise nothing is asked of the model until the visitor asks. Explanations the
 * visit already has are shown at once.
 */
export function useExplanations(id: string): Explaining {
  const language = languageOf(useLocale());
  const client = useQueryClient();
  const explained = useQuery(explanationsQuery(id, language));
  return {
    explained,
    // A failure is the query's to show, under the same key.
    ask: () => void askForExplanations(client, id, language).catch(() => {}),
  };
}

/** What the language model may do for the visitor, what it is doing, or what it wrote. */
export function ExplanationsPanel({ explained, ask }: Explaining) {
  const t = useTranslations("explanations");
  const locale = useLocale();
  const why = useExplanationErrorMessage();

  if (explained.isPending) {
    // Reading what the API keeps: nothing to offer yet, so nothing flashes by.
    return null;
  }
  if (explained.data) {
    const { model, day, unexplained } = explained.data;
    return (
      <div className="grid gap-1 text-sm text-muted-foreground">
        <p>{t("written", { model, day: formatDay(locale, day) })}</p>
        {unexplained.length > 0 && (
          <p>{t("unexplained", { rules: unexplained.join(", ") })}</p>
        )}
      </div>
    );
  }
  if (explained.fetchStatus === "fetching") {
    return (
      <p role="status" className="text-sm text-muted-foreground">
        {t("writing")}
      </p>
    );
  }
  if (explained.isError) {
    // A server without a language model will not have one when asked again.
    const noModel =
      explained.error instanceof ApiError && explained.error.status === 503;
    return (
      <Alert variant="destructive">
        <AlertDescription className="grid gap-3">
          <p>{why(explained.error)}</p>
          {!noModel && (
            <div>
              <Button variant="outline" size="sm" onClick={ask}>
                {t("again")}
              </Button>
            </div>
          )}
        </AlertDescription>
      </Alert>
    );
  }
  return (
    <div className="grid gap-3 rounded-lg border p-4 text-sm">
      <p>{t("intro")}</p>
      <p className="text-muted-foreground">{t("privacy")}</p>
      <div>
        <Button onClick={ask}>{t("ask")}</Button>
      </div>
    </div>
  );
}

/** Why the explanations were not written, in the visitor's language. */
function useExplanationErrorMessage(): (error: unknown) => string {
  const t = useTranslations("explanations.errors");
  return (error) => {
    // The browser's DOMException, which need not be an Error of this realm.
    const name =
      typeof error === "object" && error !== null && "name" in error
        ? error.name
        : null;
    if (name === "TimeoutError") {
      return t("tooSlow");
    }
    if (!(error instanceof ApiError)) {
      return t("unreachable");
    }
    switch (error.status) {
      case 404:
        return t("notFound");
      case 429:
        return t("tooMany", { seconds: error.retryAfter ?? 60 });
      case 503:
        return t("noModel");
      default:
        return t("failed");
    }
  };
}

/** One rule's explanation: what it requires, what to change, and the passages it cites. */
export function RuleExplanation({ explanation }: { explanation: Explanation }) {
  const t = useTranslations("explanations");
  if (explanation.problem || !explanation.text) {
    return <p className="text-sm text-muted-foreground">{t("problem")}</p>;
  }
  return (
    <div className="grid gap-3 border-t pt-3 text-sm">
      <p>{explanation.text}</p>
      {explanation.fix && (
        <p>
          <span className="font-medium">{t("fix")}:</span> {explanation.fix}
        </p>
      )}
      {explanation.citations.length > 0 && (
        <div className="grid gap-1">
          <h4 className="font-medium">{t("citations")}</h4>
          <ul className="grid gap-1">
            {explanation.citations.map((citation) => (
              <CitationItem key={citation.id} citation={citation} />
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** A cited passage: where it is, in which edition, and from when it applies. */
function CitationItem({ citation }: { citation: Citation }) {
  const t = useTranslations("explanations");
  const locale = useLocale();
  const from = formatDay(locale, citation.valid_from);
  const name = (
    <>
      <span lang={cyrillic(citation.label)}>{citation.label}</span>
      {citation.heading && (
        <>
          {" "}
          <span lang={cyrillic(citation.heading)}>{citation.heading}</span>
        </>
      )}
      {" — "}
      {citation.title}
    </>
  );
  return (
    <li className="grid">
      {/^https:\/\//.test(citation.source_url) ? (
        <a
          href={citation.source_url}
          target="_blank"
          rel="noreferrer"
          className="underline underline-offset-4"
        >
          {name}
        </a>
      ) : (
        <span>{name}</span>
      )}
      <span className="text-muted-foreground">
        {citation.version},{" "}
        {citation.valid_to
          ? t("validBetween", {
              from,
              to: formatDay(locale, citation.valid_to),
            })
          : t("validFrom", { from })}
      </span>
    </li>
  );
}
