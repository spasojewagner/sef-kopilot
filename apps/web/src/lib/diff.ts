/** One line of a repair's diff, or a gap where lines that do not change are left out. */
export type DiffLine =
  { kind: "gap" } | { kind: "context" | "removed" | "added"; text: string };

/** A hunk's header, `@@ -5,5 +5,5 @@`: where it starts in the document before the change. */
const HUNK = /^@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@/;

/**
 * The lines of a unified diff, as the API writes a repair's (`difflib.unified_diff`, with two
 * lines of context), and a gap above each hunk but one that starts the document. The header
 * (`--- before`, `+++ after`) is left out, and so are the hunks' numbers: the API compares
 * the invoice indented anew, two spaces a level, so that a changed value is one changed line
 * whatever the invoice's own layout, and its lines are not the lines of the file sent.
 */
export function parseDiff(diff: string): DiffLine[] {
  const lines: DiffLine[] = [];
  let header = true;
  for (const line of diff.split("\n")) {
    const hunk = HUNK.exec(line);
    if (hunk) {
      // Hunks are apart only where more lines than their context do not change.
      if (!header || Number(hunk[1]) > 1) {
        lines.push({ kind: "gap" });
      }
      header = false;
    } else if (header) {
      // `--- before` and `+++ after`; a removed line may start with `--` too.
      continue;
    } else if (line.startsWith("-")) {
      lines.push({ kind: "removed", text: line.slice(1) });
    } else if (line.startsWith("+")) {
      lines.push({ kind: "added", text: line.slice(1) });
    } else if (line.startsWith(" ")) {
      lines.push({ kind: "context", text: line.slice(1) });
    }
    // The empty string after the last newline, and "\ No newline at end of file", say nothing
    // about the invoice.
  }
  return lines;
}
