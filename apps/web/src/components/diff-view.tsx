"use client";

import { useTranslations } from "next-intl";

import { parseDiff } from "@/lib/diff";
import { cn } from "@/lib/utils";

/**
 * A repair's diff, a line to an item: what was kept, removed and added, marked as such and not
 * by colour alone, and where unchanged lines are left out. The invoice's text is shown as text.
 *
 * A line keeps its width, as XML is written; a narrow screen scrolls the lines in their box,
 * which the keyboard can reach and scroll, and which says what it holds when it is reached. A
 * group, not a region: the section around it is the page's landmark.
 */
export function DiffView({ diff, label }: { diff: string; label: string }) {
  const t = useTranslations("repair");
  return (
    <div
      role="group"
      aria-label={label}
      tabIndex={0}
      className="overflow-x-auto rounded-lg border outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
    >
      <ul className="w-max min-w-full py-1 font-mono text-xs leading-5">
        {parseDiff(diff).map((line, index) => (
          <li
            key={index}
            data-kind={line.kind}
            className={cn(
              "px-3 whitespace-pre",
              line.kind === "gap" && "bg-muted text-muted-foreground",
              line.kind === "added" && "bg-success/12",
              line.kind === "removed" && "bg-destructive/12",
            )}
          >
            {line.kind === "gap" ? (
              <>
                <span aria-hidden="true">⋯</span>
                <span className="sr-only">{t("gap")}</span>
              </>
            ) : line.kind === "added" ? (
              <ins className="no-underline">
                <span aria-hidden="true">+ </span>
                <span className="sr-only">{t("added")}: </span>
                {line.text}
              </ins>
            ) : line.kind === "removed" ? (
              <del className="no-underline">
                <span aria-hidden="true">- </span>
                <span className="sr-only">{t("removed")}: </span>
                {line.text}
              </del>
            ) : (
              <>
                <span aria-hidden="true">{"  "}</span>
                {line.text}
              </>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
