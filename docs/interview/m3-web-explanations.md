# M3 — `feat/web-explanations`

## Three questions a senior engineer would ask

**1. "The API could already explain a document. Why another endpoint for a stored invoice?"**

The page has the stored invoice's id and report, not its document. Reusing
`POST /invoices/explain` meant downloading the document and sending it back, and the API would
validate it again: a validation counted against the caller's limits, a wait for the validator's
child process, and possibly another report than the one on the page if the rule sets had changed
since. `POST /invoices/{invoice_id}/explanations` explains the stored report itself with the
same `explain_report()`, so the explanations are of what the visitor sees, the page sends an id,
and nothing is validated. It is guarded like reading the invoice, so a client finds only what
they submitted, and it counts one request to the language model and no validation. That needed
counting to take the kinds a request is, which I did as a refactor in its own commit first.

**2. "It only reads. Why is it a POST?"**

Because it costs. GET is safe in HTTP's sense: browsers prefetch links, chat apps fetch them for
previews, crawlers follow them, caches store answers and hand them to the next person. Every one
of those would spend the language model's requests, of which the free tier has few. A POST is
sent only when a client means to send it, and no cache keeps its answer; it says `no-store` as
well. The cost is that the method no longer tells a reader it changes nothing, so the summary
and description in the OpenAPI document say that nothing is stored.

**3. "How do you keep the UI from burning the model's budget?"**

Nothing is asked until the visitor presses "Objasni pravila": the query is `enabled` only after
that. Once written, the explanations are never asked for again by the page: infinite `staleTime`
and `gcTime`, no retry, so going to the list and back costs nothing and a failure waits for the
visitor to try again. The key has one entry per language under the invoice's key, so invalidating
the invoice drops them. The server still decides: limits per member and per organization, 429
with `Retry-After`, which the page turns into the seconds to wait, and a 503 without a model, for
which the page does not offer to try again. Before the visitor asks, the page says what is sent:
each rule's message, which may quote the invoice, and passages of the regulations.

## The one concept to explain unaided

**A read that costs is asked for on purpose.** On the server it is a POST, never cached; on the
page it waits for the visitor, and once paid for it is kept, never asked for again by itself.

## Supporting facts worth remembering

- `POST /invoices/{invoice_id}/explanations?language=sr|en`: 404 outside the caller's scope, 429
  with `Retry-After`, 503 without a model; at most `SEF_MAX_EXPLANATIONS` (5) rules, the rest in
  `unexplained`; 30 s for the model by default, so the page waits a minute.
- The API's test stores an invoice, replaces its document behind the API's back, and checks that
  the report explained is still the stored one: proof that nothing was validated again.
- Counting: `count(request, caller, *kinds)`, with `VALIDATION` and `MODEL_REQUEST` each a pair
  of the caller's limit and the organization's. `count_validation()` is a shorthand for it.
- The page's key: `["invoices", "one", id, "explanations", language]`. Citations link only to
  `https` sources, open in a new tab with `rel="noreferrer"`, and labels in Cyrillic, as the law
  prints them, carry `lang="sr-Cyrl"`.
- The tests' cache now has the pages' defaults: a test that a page asks nothing again used to
  pass because it looked before the page had asked. It waits a moment now (`aMoment()`).
