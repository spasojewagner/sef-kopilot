# 40. Explanations of a stored invoice are kept with it, by the digest of the report they explain

- Status: accepted; amends [0029](0029-explanations-of-a-stored-invoice.md), under which nothing
  was stored
- Date: 2026-11-07
- Deciders: the team (the backlog's item, moved to M4 by Marko Spasojević on 2026-11-07)
- Technical story: milestone M4, branch `feat/api-explanations-kept`; the explanations of
  ADR-0021 and ADR-0029, the retention of ADR-0039

## Context and problem statement

ADR-0029 explains a stored invoice's report when a visitor asks, and stores nothing: a reload,
or another member's visit, asks the language model again for the same text, spending seconds and
a free tier's requests. The backlog planned explanations written once and kept with the report.
What is kept, when is a kept set still the invoice's, who reads it, and what writes it?

## Decision drivers

- The explanations shown are of the report shown.
- The model is asked once a report and a language, not once a view.
- A rule the model could not explain is asked about again.
- Kept explanations may quote the invoice: they live and go with it.
- No new moving part: no job kind, no stream for the page to follow.

## Considered options

1. **Kept a set an invoice and a language, with the digest of the report and the day whose law
   it cites; written in the request that asks, as before; only whole sets.** Chosen.
2. Written by a job when the invoice is stored or validated again.
3. Written by a job when a visitor asks, which the page follows over its event stream.
4. Kept by the document's digest, or by when the invoice was last validated.
5. An HTTP cache before the route.

## Decision outcome

**The table `explanations`** holds one set an invoice and a language: the digest of the report
it explains (SHA-256 of the report as the API writes it), the day whose law it cites, the model
that wrote it, the explanations and the rules left for a later request, and when it was written.
It goes with its invoice and its organization (`ON DELETE CASCADE`), so a member's deletion and
the retention period of ADR-0039 take it too.

**A kept set is the invoice's** while its digest and day are the invoice's now. The report
changes when a repair is approved or the invoice is validated again under other rule sets; the
day changes only for an invoice that cannot be read, which is explained by the law of the day it
is asked about.

**`POST /invoices/{invoice_id}/explanations`** finds the invoice, then reads a kept set: the
model is not asked, nothing is counted, and a server without a model answers too. Without one,
it asks the model as ADR-0029 does, and keeps the set when every rule asked about is explained,
in place of the set kept before in that language. **`GET`** reads the kept set alone and never
asks the model; it answers 204, with no content, when none is kept. A 404 would say the invoice
is not there, and a browser logs every 404 as an error: a page that reads the kept set as it
opens would log one for every report nobody has explained yet. Every answer with explanations
says when they were written (`written_at`).

Two first requests at the same moment both ask the model, and the second set written replaces
the first: holding a lock across a model's answer would hold a connection for seconds, to save a
request that a rare race spends. An invoice deleted while its explanations are written has its
row locked before the insert, and nothing is kept when it is gone.

### Consequences

Good:

- One request to the model a report and a language, for every member; a reload costs nothing.
- Kept explanations are read on a server whose model is gone, its key revoked say.
- The page can show explanations at once when they are kept (`GET`), without spending anything.

Bad / accepted:

- A kept set cites the passages as they were when it was written. A new edition of the corpus
  does not rewrite it until the report changes; each citation names its edition and its dates,
  so what it cites stays exact.
- A kept set names the model that wrote it after `SEF_LLM_MODEL` changes, and a change of
  `SEF_MAX_EXPLANATIONS` does not rewrite it.
- A set with one rule unexplained is not kept, so that rule costs a request each time it is asked
  about.
- The backlog said the explanations would be written by a job; they are written in the request,
  for the reasons below.

## Pros and cons of the options

### Written by a job when the invoice is stored or validated again

- Good: ready when the page opens, for every reader.
- Bad: every stored invoice spends the model's requests, read or not, in a language chosen ahead
  or in both, and a revalidation of the organization's invoices would spend them by the hundred.
  ADR-0029 rejected it for that reason, which holds.

### Written by a job when a visitor asks

- Good: a request that never waits for the model.
- Bad: the visitor waits for the explanations either way. The request already has a deadline
  (`SEF_EXPLANATION_SECONDS`) and answers with what it could write; a job would add a job kind,
  its attempts, and an event stream the page must follow, for nothing the visitor sees.

### Kept by the document's digest, or by when the invoice was validated

- Good: columns the invoice already has.
- Bad: the document's digest does not change when the invoice is validated again under new rule
  sets, which can give another report; when it was validated changes with every revalidation,
  even one that gives the same report, and would discard good explanations. The report's digest
  names exactly what the explanations explain.

### An HTTP cache before the route

- Good: no table.
- Bad: the route is a POST, which caches do not keep, and its answers are `no-store`, since they
  may quote the invoice; and a cache is per browser, not per organization.
