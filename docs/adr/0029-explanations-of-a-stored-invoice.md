# 29. Explanations of a stored invoice: its report explained, when the visitor asks

- Status: accepted
- Date: 2026-11-06
- Deciders: Marko Spasojević
- Technical story: milestone M3, branch `feat/web-explanations`; the explanations and citations
  of ADR-0021 on the report's page of ADR-0028

## Context and problem statement

The report's page shows a stored invoice's latest report (ADR-0028). Next to each rule it should
show what ADR-0021 writes: what the rule requires, why the invoice fails it and what to change,
citing the passages of the regulations that apply on the invoice's day. The API wrote them only
for a document in the request body, `POST /invoices/explain`, which validates it first. The page
has the stored invoice's id and report, not its document. Each explanation also costs requests to
a language model whose free tier is small, behind limits per member and per organization
(SECURITY V2), and takes seconds. Where do the page's explanations come from, and when does the
page ask for them?

## Decision drivers

- The rules explained are the rules the visitor sees.
- The model's requests are spent on what someone reads, not on every view of a page.
- No document carried through the browser and back.
- Nothing more of the invoice sent to the model than ADR-0021 sends: each rule's first violation.
- Explanations in the page's language, Serbian or English.
- Room for the backlog's next step, explanations written once and kept with the report.

## Considered options

Where they come from:

1. **A route that explains a stored invoice's report, `POST /invoices/{invoice_id}/explanations`.**
   Chosen.
2. The page reads the document (`GET /invoices/{id}/content`) and sends it to
   `POST /invoices/explain`.
3. Explanations written by a job when the invoice is stored, and kept with its report.

When the page asks:

1. **When the visitor asks, once a language, and kept for the visit.** Chosen.
2. As soon as the report's page opens.

## Decision outcome

**The route** explains the stored invoice's latest report as `POST /invoices/explain` explains a
fresh one (`explain_report`, ADR-0021): the passages that apply on the issue date, in `sr` or
`en`, at most `SEF_MAX_EXPLANATIONS` rules, the rest named. The invoice is not validated again,
and the report comes back with the explanations. It is guarded like reading the invoice
(`invoices:submit`, and a client sees only what they submitted): 404 outside that, 503 when the
server has no model. It counts one request to the language model, per caller and per
organization, and no validation: counting takes the kinds a request is (`count()`, a refactor of
`count_validation()`). Nothing is stored, and the answer is `no-store`. It is a POST, not a GET,
because each call costs the model's requests: no cache, prefetcher or crawler may trigger it.

**The page** asks with TanStack Query, under the key `["invoices", "one", id, "explanations",
language]`, which is under the invoice's, so that what changes the invoice drops its
explanations too. The query runs only once the visitor has pressed "Objasni pravila"; it never
asks again by itself (`staleTime` and `gcTime` infinite, no retry), so going to the list and back
shows the same explanations, and a reload forgets them. Before the visitor asks, the page says
what the model is sent: each rule's message, which may quote the invoice, and passages of the
regulations. Each rule's card then shows its explanation, what to change, and the passages cited,
with their editions, the days they apply from, and links to their official sources (only `https`
ones); labels and headings in Cyrillic, as the law prints them, are marked `lang="sr-Cyrl"`. The
page names the model and the day whose law was cited, the rules left for a later request, and why
none were written: too many requests (with the seconds to wait), no model on the server (with no
offer to try again), no answer within a minute, or no API.

### Consequences

Good:

- The explanations are of the report on the page, even after the rule sets change.
- One request to the model per invoice and language, and only when the visitor wants it.
- No validation spent and no document moved: the page sends an id.
- The stored explanations of the backlog can be read through the same route, and the page would
  not change.

Bad / accepted:

- Two routes write explanations, one of a document and one of a stored invoice. They share
  `explain_report()` and its answer, and the tests of each check what differs: the body, and
  what is counted.
- A reload, or another member's visit, asks the model again until explanations are kept.
- A POST that changes nothing stored, which HTTP calls unsafe all the same. That is the point:
  it spends something.

## Pros and cons of the options

### The page sends the document back

- Good: no change to the API.
- Bad: the browser downloads the document and uploads it again, up to the API's size limit both
  ways. The API validates it again, which counts as a validation, waits for the validator, and
  may give another report than the stored one if the rule sets have changed since. Two requests
  and more code on the page.

### Explanations written when the invoice is stored

- Good: ready when the page opens, written once for every reader.
- Bad: every stored invoice spends the model's requests, read or not, and in a language chosen
  ahead, or in both. It needs a job, a migration and storage: the backlog's item after M3, which
  this route will serve.

### As soon as the page opens

- Good: nothing to press.
- Bad: every view spends the model's requests, reloads and other members' views included, and
  keeps the visitor waiting seconds they did not ask to wait. The free tier's limits would be
  spent on pages nobody reads.
