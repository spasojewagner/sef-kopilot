# M4 — `feat/api-explanations-kept`

## Three questions a senior engineer would ask

**1. "Why key the kept explanations by the report's digest?"**

Because the report is what they explain. It changes when a repair is approved, and when the
invoice is validated again under other rule sets. The document's digest misses the second case:
the same document can get another report. When the invoice was last validated misses nothing,
but changes with every revalidation, even one that gives the same report, and would throw away
good explanations. The digest of the report names exactly the thing explained, and a stale set
is found by a comparison, with nothing to remember to delete.

**2. "The backlog said a job would write them. Why not?"**

A job written when an invoice is stored would spend the model on invoices nobody reads, which
ADR-0029 already rejected. A job started when a visitor asks changes nothing the visitor sees:
they wait for the explanations either way, and the request already has a deadline and answers
with what it could write. The job would add a job kind, attempts and an event stream to follow.
The ADR records the departure from the backlog and why.

**3. "Two members press 'Explain' at the same moment. What happens?"**

Both ask the model, both write, and the upsert leaves one set a language. Holding a lock while
the model answers would hold a database connection for seconds, to save one request in a rare
race. An invoice deleted meanwhile is checked under a lock on its row before the insert, so no
set outlives its invoice.

## The one concept to explain unaided

**Content addressing**: key what is derived by the digest of what it was derived from, and
invalidation becomes a comparison instead of a list of places that must remember to delete.

## Supporting facts worth remembering

- One set an invoice and a language; only sets in which every rule asked about was explained.
- `GET /invoices/{invoice_id}/explanations` never asks the model; `POST` reads a kept set first.
- Kept explanations go with their invoice, whether a member deletes it or its retention period
  runs out.
