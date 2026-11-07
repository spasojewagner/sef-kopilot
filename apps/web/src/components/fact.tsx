import type { ReactNode } from "react";

/**
 * One fact in the header of a page, inside its `<dl>`: what it is, its value under it, a note on
 * the value if it needs one, and what the visitor may do about it.
 */
export function Fact({
  term,
  value,
  note,
  children,
}: {
  term: string;
  value: string;
  note?: string;
  children?: ReactNode;
}) {
  return (
    <div className="grid gap-1">
      <dt className="text-muted-foreground">{term}</dt>
      <dd className="font-medium">{value}</dd>
      {note !== undefined && <dd className="text-muted-foreground">{note}</dd>}
      {children !== undefined && <dd>{children}</dd>}
    </div>
  );
}
