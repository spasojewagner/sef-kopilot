# M3 — `feat/web-repair-suggestion`

## Three questions a senior engineer would ask

**1. "Three different refusals all come back as 409. How does the page tell them apart?"**

By a reason the API now names in every 409 of the repairs: `nothing-to-repair`,
`too-many-waiting`, `invoice-changed`, `decided`, `changes-nothing`, `outcome-changed`, beside
the English detail. Before, the page would have had to compare the detail's text, which is
prose for people and may be reworded, and every other client, an ERP or an MCP tool, would have
copied the same comparisons. I kept the status: each of them is a conflict with the state of the
invoice or of the repair, which is what 409 means, and other statuses would mislead HTTP
clients. The routes raise one `ConflictError`, one handler answers it, the OpenAPI document
names the model for all four routes, and a test pins them, so a new 409 cannot slip in without
a reason.

**2. "You used a query for the explanations. Why a mutation here?"**

Because a suggestion creates something. Asking for explanations twice gives the same
explanations, so a query, kept under a key and never asked for again, fits. Asking for a repair
twice creates two repairs on the server, each waiting for a decision. A query may run again
whenever its key is wanted and stale, on a remount or when the window regains focus; a mutation
runs only when called. Its answer is the repair the API kept, so I write it into the cache
under that repair's key, which opens its page at once, and invalidate the list, which has one
more now.

**3. "What happens if the visitor leaves the page while the model works?"**

The request goes on; the API keeps the repair either way. The cache learns of it in the hook's
`onSuccess`, which runs regardless, so the list is right when they come back. The navigation to
the repair is in the `onSuccess` given to `mutate()`, which TanStack Query calls only while the
component that called it is mounted, so a visitor who went to the list stays there. Nothing is
retried by itself: the model's requests are spent only when the visitor presses the button.

## The one concept to explain unaided

**If a request ran twice, what would there be twice?** Nothing: it is a read, a query. A second
thing on the server: it is a write, a mutation, whose answer the cache learns from and whose
effects it marks stale.

## Supporting facts worth remembering

- `POST /invoices/{invoice_id}/repairs/suggestion?language=sr|en`: 201 with the repair and
  `Location`; 409 with a reason; 422 for no patch a repair keeps; 429 and a busy validator's 503
  with `Retry-After`; 502 for an unusable answer; 503 without `Retry-After` for no model or no
  validator; 504 when no round was done in time. The page waits 60 s.
- Offered only for an invalid invoice that is XML (`isXml`: its XML layer ran and found
  nothing), since patches apply to XML only.
- The page says first what the model is sent: the violations, whose messages may quote the
  invoice, and the invoice's fields around them; nothing else of it.
- Found while checking in a browser: a stand-in model that rewrote the type code with the value
  it already had got a repair kept that changes nothing, so it waits for a decision that cannot
  approve it. The backlog has the repairer drop such patches.
