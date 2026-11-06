/** One fact in the header of a page, inside its `<dl>`: what it is, and its value under it. */
export function Fact({ term, value }: { term: string; value: string }) {
  return (
    <div className="grid gap-1">
      <dt className="text-muted-foreground">{term}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}
