# 26. A read that costs: POST, asked for on purpose, kept once paid for

An explanation changes nothing on the server: it reads a stored report and the passages of the
law, and writes nothing down. It is still not free. Each one spends requests to a language model
whose free tier is small, behind limits per member and per organization, and takes seconds. Two
habits that suit ordinary reads would waste it.

**GET promises that asking is harmless.** HTTP calls GET *safe*: a client may send it whenever
it likes, and many do without anyone asking. A browser prefetches links, a chat app fetches a
link to show its preview, a crawler follows everything, a cache stores the answer and serves it
to the next person. A GET that spends money spends it for all of them. So
`/invoices/{invoice_id}/explanations` is a POST, though it stores nothing: a POST is sent only
when something means to send it, and no cache keeps its answer, which says `no-store` besides.

```text
GET  /invoices/{id}                 safe: read as often as anyone likes
GET  /invoices/{id}/content         safe: the document, byte for byte
POST /invoices/{id}/explanations    not safe: each call spends the model's requests
```

**A page fetches by itself; this query must not.** TanStack Query fetches when a component
mounts, again when the data goes stale, when the window regains focus, and once more after a
failure. Each is a good default for a report, and each would spend the model's requests here.
The explanations' query turns them all off:

```ts
useQuery({
  ...explanationsQuery(id, language), // staleTime and gcTime: Infinity; retry: false
  enabled: asked,                     // false until the visitor presses the button
});
```

`enabled` keeps the query idle until the visitor asks. An infinite `staleTime` means an answer
never needs asking for again, and an infinite `gcTime` keeps it in memory after the page is
left, so going to the list and back costs nothing. A failure is shown with a button to try
again, which the visitor presses or not. The key, `["invoices", "one", id, "explanations",
language]`, has one entry per language, under the invoice's: invalidating the invoice drops its
explanations too.

**The server still decides.** The page only avoids waste. The API counts every request against
the caller's limit and the organization's, says 429 with `Retry-After` beyond them, and the page
repeats the seconds to wait. A server without a model answers 503, and the page does not offer
to try again, since asking again would not change it.

Why not `useMutation`? A mutation is for a change: its result belongs to the component that made
it, and no other part of the page can find it by a key. These explanations are a read that the
visitor pays for once and wants to keep.

The question to ask of a request that costs: who can send it without meaning to, and what in
the client sends it again by itself?
